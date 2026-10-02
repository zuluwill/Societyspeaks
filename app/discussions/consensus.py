# app/discussions/consensus.py
"""
Consensus & Clustering API Routes (Phase 3)

Provides endpoints for running consensus analysis and viewing results
"""
from flask import abort, render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app, make_response
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Discussion, ConsensusAnalysis, ConsensusJob, Statement, StatementVote
from app.lib.participation_metrics import visible_statement_vote_filters
from app.api.utils import get_discussion_participant_count
from app.lib.vote_identity import anonymous_fingerprint_aliases_for_daily_lookup
from app.lib.consensus_engine import can_cluster, get_consensus_execution_plan
from app.discussions.jobs import enqueue_consensus_job
from app.discussions.thresholds import consensus_thresholds_dict, CONSENSUS_VIEW_RESULTS_MIN_VOTES
from app.programmes.permissions import can_view_programme
from datetime import datetime, timedelta
from sqlalchemy import func, or_
from app.lib.time import utcnow_naive
import logging
from flask_babel import gettext as _

consensus_bp = Blueprint('consensus', __name__)
logger = logging.getLogger(__name__)

# Minimum votes required to unlock consensus analysis
PARTICIPATION_THRESHOLD = CONSENSUS_VIEW_RESULTS_MIN_VOTES


def _demo_discussion_ids():
    """
    Parse the CONSENSUS_DEMO_DISCUSSION_IDS config (comma-separated ints)
    into a set for participation-gate bypasses. Empty by default; kept
    behind config so promotion across environments does not require code
    changes.
    """
    raw = str(current_app.config.get('CONSENSUS_DEMO_DISCUSSION_IDS', '') or '').strip()
    if not raw:
        return set()
    ids = set()
    for chunk in raw.split(','):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            ids.add(int(chunk))
        except ValueError:
            logger.warning("Ignoring non-int discussion id in CONSENSUS_DEMO_DISCUSSION_IDS: %r", chunk)
    return ids


def _oversize_publishability_thresholds():
    """Centralized publication thresholds for oversize analyses."""
    return {
        'min_stability_runs': int(current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_RUNS', 3)),
        'min_stability_mean_ari': float(current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_ARI', 0.30)),
    }


def _full_matrix_publishability_thresholds():
    """Centralized publication thresholds for full-matrix analyses."""
    return {
        'min_stability_mean_ari': float(current_app.config.get('CONSENSUS_FULL_MATRIX_MIN_STABILITY_ARI', 0.20)),
    }


def _assess_analysis_publishability(analysis):
    """
    Gate every analysis — full-matrix AND oversize — on its stability.

    Oversize keeps its stricter original thresholds (minimum-runs +
    mean-ARI). Full-matrix applies a looser mean-ARI floor because the
    inputs are less sampled. Either way, a published result comes with a
    reproducibility guarantee rather than whatever a single random seed
    happened to produce.
    """
    metadata = (analysis.cluster_data or {}).get('metadata', {})
    mean_ari_raw = metadata.get('stability_mean_ari')
    try:
        mean_ari = float(mean_ari_raw) if mean_ari_raw is not None else 1.0
    except (TypeError, ValueError):
        mean_ari = 0.0
    runs = int(metadata.get('stability_runs', 0) or 0)

    if metadata.get('oversize_mode'):
        thresholds = _oversize_publishability_thresholds()
        if runs < thresholds['min_stability_runs']:
            return (
                False,
                (
                    "Large-scale analysis is temporarily withheld: insufficient stability runs "
                    f"(have {runs}, need {thresholds['min_stability_runs']})."
                ),
            )
        if mean_ari < thresholds['min_stability_mean_ari']:
            return (
                False,
                (
                    "Large-scale analysis is temporarily withheld: stability is below publication threshold "
                    f"(mean ARI {mean_ari:.3f}, need >= {thresholds['min_stability_mean_ari']:.3f})."
                ),
            )
        return True, None

    # Full-matrix path: only gate if we actually measured stability.
    # Older stored analyses (before the full-matrix stability roll-out)
    # will not carry stability_mean_ari; treat them as publishable so we
    # do not retroactively withhold historical results.
    if mean_ari_raw is None:
        return True, None
    thresholds = _full_matrix_publishability_thresholds()
    if mean_ari < thresholds['min_stability_mean_ari']:
        return (
            False,
            (
                "Analysis is temporarily withheld: cluster structure is not reproducible across re-seeded runs "
                f"(mean ARI {mean_ari:.3f}, need >= {thresholds['min_stability_mean_ari']:.3f}). "
                "Re-running analysis after more votes arrive will usually fix this."
            ),
        )
    return True, None


def _invalidate_snapshot_cache(discussion_id):
    try:
        from app.api.utils import invalidate_partner_snapshot_cache
        invalidate_partner_snapshot_cache(discussion_id)
    except Exception:
        pass


def get_user_vote_count(discussion_id):
    """
    Get the number of statements a user has voted on in this discussion.
    Works for both authenticated and anonymous users.
    Counts only votes on visible statements (not deleted, mod_status >= 0),
    aligned with published participation metrics.

    For authenticated users, also counts any votes made before login
    (via any unified anonymous fingerprint alias).

    Returns: (vote_count, identifier_type)
        - vote_count: number of distinct visible statements voted on
        - identifier_type: 'user' or 'anonymous'
    """
    _vis = visible_statement_vote_filters(Statement)

    if current_user.is_authenticated:
        user_stmt_ids = [
            r[0]
            for r in StatementVote.query.filter_by(
                discussion_id=discussion_id,
                user_id=current_user.id,
            )
            .join(Statement, StatementVote.statement_id == Statement.id)
            .filter(*_vis)
            .with_entities(StatementVote.statement_id)
            .distinct()
            .all()
        ]
        user_set = set(user_stmt_ids)
        try:
            aliases = anonymous_fingerprint_aliases_for_daily_lookup()
            if aliases:
                anon_stmt_ids = [
                    r[0]
                    for r in StatementVote.query.filter(
                        StatementVote.discussion_id == discussion_id,
                        StatementVote.user_id.is_(None),
                        StatementVote.session_fingerprint.in_(aliases),
                    )
                    .join(Statement, StatementVote.statement_id == Statement.id)
                    .filter(*_vis)
                    .with_entities(StatementVote.statement_id)
                    .distinct()
                    .all()
                ]
                user_set |= set(anon_stmt_ids)
        except Exception as e:
            logger.debug(f"Could not merge anonymous aliases for auth user: {e}")
        return len(user_set), "user"

    try:
        aliases = anonymous_fingerprint_aliases_for_daily_lookup()
        if not aliases:
            return 0, "anonymous"
        anon_stmt_ids = [
            r[0]
            for r in StatementVote.query.filter(
                StatementVote.discussion_id == discussion_id,
                StatementVote.user_id.is_(None),
                StatementVote.session_fingerprint.in_(aliases),
            )
            .join(Statement, StatementVote.statement_id == Statement.id)
            .filter(*_vis)
            .with_entities(StatementVote.statement_id)
            .distinct()
            .all()
        ]
        return len(anon_stmt_ids), "anonymous"
    except Exception as e:
        logger.debug(f"Could not get fingerprint aliases: {e}")
        return 0, "anonymous"


# 10% more participants, or any newly-voted statement, is enough drift to
# suggest a re-run. Below that the picture would not visibly change.
ANALYSIS_PARTICIPANT_DRIFT_RATIO = 1.1


def _analysis_metadata(analysis):
    cluster = getattr(analysis, 'cluster_data', None) or {}
    if not isinstance(cluster, dict):
        return {}
    meta = cluster.get('metadata') or {}
    return meta if isinstance(meta, dict) else {}


def _live_voted_statement_count(discussion_id):
    """Statements that would be columns of ``build_vote_matrix``.

    Counted from vote rows, not the denormalised ``vote_count_*`` columns.
    Those counters can run ahead of (or behind) the rows the engine actually
    clustered, which made the staleness banner lie.
    """
    # Filters mirror ``build_vote_matrix`` exactly: scoped by
    # ``StatementVote.discussion_id`` (not ``Statement.discussion_id``), joined
    # to Statement only for ``is_deleted``, and skipping vote rows with neither
    # identifier — those the matrix builder drops. This also lets the query use
    # idx_vote_discussion_statement.
    return (
        db.session.query(func.count(func.distinct(StatementVote.statement_id)))
        .join(Statement, StatementVote.statement_id == Statement.id)
        .filter(
            StatementVote.discussion_id == discussion_id,
            Statement.is_deleted.is_(False),
            or_(
                StatementVote.user_id.isnot(None),
                StatementVote.session_fingerprint.isnot(None),
            ),
        )
        .scalar()
        or 0
    )


def detect_analysis_drift(discussion, analysis):
    """
    Compare a stored analysis against live participation.

    Both sides of each comparison must be measured the same way, or the
    "newer votes are in" notice fires on essentially every analysis:

      * Full-matrix ``analysis.statements_count`` is the vote-matrix column
        count — statements with at least one identifiable vote. The live
        figure is that same count, from ``statement_vote`` rows.
      * Oversize analyses store the full non-deleted catalog instead
        (``metadata.oversize_mode``). Compare catalogs, or a new statement
        that nobody has voted on yet is invisible and a voted-only count
        never exceeds the old catalog.
      * ``analysis.participants_count`` counts distinct voters, so it must be
        compared with a distinct-voter count, never with a sum of votes. Every
        participant casts many votes, so a votes-vs-participants test is true
        as soon as the average participant votes twice.

    Scope matches the engine: non-deleted statements in any moderation state.

    Returns a dict with current/analysed counts for both dimensions and
    ``is_stale``.
    """
    oversize = bool(_analysis_metadata(analysis).get('oversize_mode'))
    if oversize:
        current_stmt_count = Statement.query.filter_by(
            discussion_id=discussion.id,
            is_deleted=False,
        ).count()
    else:
        current_stmt_count = _live_voted_statement_count(discussion.id)
    current_participant_count = get_discussion_participant_count(
        discussion,
        include_deleted_statement_votes=False,
        min_mod_status=None,
    )
    analysed_stmt_count = int(getattr(analysis, 'statements_count', 0) or 0)
    analysed_participants = int(getattr(analysis, 'participants_count', 0) or 0)

    has_new_statements = current_stmt_count > analysed_stmt_count
    # Strictly more participants *and* at least the drift ratio. The ratio
    # alone is not enough: truncating 1 * 1.1 to an int made "1 participant,
    # still 1 participant" read as drift.
    has_new_participants = (
        analysed_participants > 0
        and current_participant_count > analysed_participants
        and current_participant_count
        >= analysed_participants * ANALYSIS_PARTICIPANT_DRIFT_RATIO
    )

    return {
        'current_stmt_count': current_stmt_count,
        'analysed_stmt_count': analysed_stmt_count,
        'current_participant_count': current_participant_count,
        'analysed_participants': analysed_participants,
        'has_new_statements': has_new_statements,
        'has_new_participants': has_new_participants,
        'is_stale': has_new_statements or has_new_participants,
    }


def _safe_statement_id(entry):
    """Integer statement id, or None when the stored entry is unusable."""
    if not isinstance(entry, dict):
        return None
    raw = entry.get('statement_id')
    if raw is None or isinstance(raw, bool):
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _statement_is_public(stmt):
    """Published consensus views omit deleted and negatively moderated statements."""
    if stmt is None or stmt.is_deleted:
        return False
    return (stmt.mod_status or 0) >= 0


def _metrics_by_statement_id(entries):
    """statement_id -> engine metrics. Later duplicates keep the last entry."""
    metrics = {}
    for entry in entries or []:
        sid = _safe_statement_id(entry)
        if sid is None:
            continue
        metrics[sid] = entry
    return metrics


def _ranked_public_statements(entries):
    """Statements in the engine's ranked order, published-visible only.

    ``Statement.query.in_()`` returns rows in arbitrary order, so the safest
    signal (the engine sorts by Wilson lower bound) has to be re-applied here.
    """
    ids = []
    seen = set()
    for entry in entries or []:
        sid = _safe_statement_id(entry)
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        ids.append(sid)
    if not ids:
        return []
    by_id = {
        stmt.id: stmt
        for stmt in Statement.query.filter(Statement.id.in_(ids)).all()
    }
    return [by_id[sid] for sid in ids if _statement_is_public(by_id.get(sid))]


def _unique_statements(statements):
    """Statement objects, de-duplicated by id, skipping missing rows."""
    seen = set()
    unique = []
    for stmt in statements or []:
        if stmt is None:
            continue
        sid = getattr(stmt, 'id', None)
        if sid is None or sid in seen:
            continue
        seen.add(sid)
        unique.append(stmt)
    return unique


def _published_translations(discussion, statements):
    """Cached statement and discussion copy for the viewer's language.

    English viewers get an empty map. Templates then fall back to the
    canonical English content, which is the same contract as the results page.

    ``incomplete`` says whether the "translation in progress" notice is
    warranted. It is computed here, over the *de-duplicated* set of
    statements the page will show, because the templates cannot do it
    safely: they summed the per-section lengths and compared that with
    ``translation_map|length``, which is keyed by unique statement id. A
    statement that is both a consensus statement and a bridge — the normal
    case, since anything every group agrees on passes both gates — made the
    sum exceed the map for good, so a fully translated page permanently
    advertised that it was "showing in English".

    Returns ``(translation_map, discussion_translation, view_lang, incomplete)``.
    """
    from app.lib.translation import (
        get_cached_discussion_translation,
        get_cached_statement_translations,
        resolve_language,
    )

    view_lang = resolve_language(request)
    if view_lang == 'en':
        return {}, None, view_lang, False

    unique = _unique_statements(statements)
    translation_map = (
        get_cached_statement_translations(unique, view_lang) if unique else {}
    )
    discussion_translation = get_cached_discussion_translation(discussion, view_lang)
    incomplete = discussion_translation is None or any(
        stmt.id not in translation_map for stmt in unique
    )
    return translation_map, discussion_translation, view_lang, incomplete


def _axis_loading_entries(stmts_by_id, translation_map):
    """Axis-label lookup keyed by both int and str ids.

    Stored loadings are ints, but a JSON round-trip can surface them as
    strings. Snippets prefer the viewer's cached translation.
    """
    entries = {}
    for stmt in (stmts_by_id or {}).values():
        if stmt is None:
            continue
        text = (translation_map or {}).get(stmt.id) or (stmt.content or '')
        short = (text[:80] + '…') if len(text) > 80 else text
        entry = {
            'statement_id': stmt.id,
            'content': text,
            'short': short,
        }
        entries[stmt.id] = entry
        entries[str(stmt.id)] = entry
    return entries


def build_consensus_ui_state(discussion, precomputed_metrics=None, participant_count=None):
    """
    Build a single, consistent consensus progress payload for UI consumers.

    Returns:
        dict with:
          - user_vote_count
          - participation_threshold
          - is_consensus_unlocked (True for creator, site admin, or enough votes —
            aligned with ``view_results`` participation exceptions)
          - consensus_progress
    """
    thresholds = consensus_thresholds_dict()
    user_vote_count, __ = get_user_vote_count(discussion.id)
    participation_threshold = PARTICIPATION_THRESHOLD
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)

    # Compute visibility filter once, only when at least one query path will run.
    if precomputed_metrics is None or participant_count is None:
        can_view_unapproved = current_user.is_authenticated and (
            current_user.id == discussion.creator_id or getattr(current_user, 'is_admin', False)
        )
        min_mod_status = None if can_view_unapproved else 0
    else:
        min_mod_status = None  # both args pre-supplied; no queries will run

    if precomputed_metrics is not None:
        total_votes = int(precomputed_metrics.get('total_votes') or 0)
        statement_count = int(precomputed_metrics.get('statement_count') or 0)
    else:
        statement_scope = Statement.query.filter(
            Statement.discussion_id == discussion.id,
            Statement.is_deleted.is_(False)
        )
        if min_mod_status is not None:
            statement_scope = statement_scope.filter(Statement.mod_status >= min_mod_status)

        total_votes = statement_scope.with_entities(
            func.coalesce(func.sum(Statement.vote_count_agree), 0) +
            func.coalesce(func.sum(Statement.vote_count_disagree), 0) +
            func.coalesce(func.sum(Statement.vote_count_unsure), 0)
        ).scalar() or 0

        statement_count = statement_scope.with_entities(
            func.count(Statement.id)
        ).scalar() or 0

    if participant_count is None:
        participant_count = get_discussion_participant_count(
            discussion,
            include_deleted_statement_votes=False,
            min_mod_status=min_mod_status,
        )

    return {
        'user_vote_count': int(user_vote_count or 0),
        'participation_threshold': int(participation_threshold),
        'is_consensus_unlocked': bool(
            is_creator or is_admin or user_vote_count >= participation_threshold
        ),
        'consensus_progress': {
            'participant_count': int(participant_count or 0),
            'min_participants': int(thresholds.get('min_participants', 7)),
            'total_votes': int(total_votes or 0),
            'min_total_votes': int(thresholds.get('min_total_votes', 20)),
            'statement_count': int(statement_count or 0),
            'recommended_statements': int(thresholds.get('recommended_statements', 10)),
        }
    }


@consensus_bp.route('/discussions/<int:discussion_id>/consensus/analyze', methods=['POST'])
@login_required
@limiter.limit("3 per hour")
def trigger_analysis(discussion_id):
    """
    Trigger consensus analysis for a discussion
    Rate limited to prevent abuse (computationally expensive)
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Only discussion owner can trigger analysis
    if discussion.creator_id != current_user.id:
        flash(_("Only the discussion owner can run consensus analysis"), "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if ready for queueing (full matrix OR oversize fallback mode).
    plan = get_consensus_execution_plan(discussion_id, db)
    if not plan['is_ready']:
        flash(f"Cannot run analysis: {plan['message']}", "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if recent analysis exists (avoid re-running too frequently)
    recent_analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if recent_analysis:
        time_since_last = utcnow_naive() - recent_analysis.created_at
        if time_since_last < timedelta(hours=1):
            flash(f"Analysis was run {int(time_since_last.total_seconds() / 60)} minutes ago. Please wait before running again.", "info")
            return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
    
    try:
        job, created, message = enqueue_consensus_job(
            discussion_id=discussion_id,
            requested_by_user_id=current_user.id,
            reason='manual_trigger'
        )
        if created:
            if plan.get('mode') == 'sampled_incremental':
                flash(
                    "Consensus analysis queued in oversize mode (sampled clustered approximation). "
                    "Results will appear once processing completes.",
                    "success"
                )
                return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
            flash(_("Consensus analysis queued. Results will appear once processing completes."), "success")
        else:
            flash(message or "Analysis is already queued for this discussion.", "info")
        return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
    except Exception as e:
        logger.error(f"Error queueing consensus analysis: {e}", exc_info=True)
        flash(_("An error occurred while queueing analysis. Please try again later."), "danger")
        return redirect(url_for('discussions.view_discussion',
                              discussion_id=discussion.id,
                              slug=discussion.slug))


@consensus_bp.route('/discussions/<int:discussion_id>/consensus')
def view_results(discussion_id):
    """
    View consensus analysis results page
    Shows clusters, consensus statements, bridges, and divisive points
    
    Participation Gate: Users must vote on at least PARTICIPATION_THRESHOLD 
    statements before viewing analysis results. This prevents anchoring bias
    where seeing results influences voting behavior.
    
    Exceptions:
    - Discussion creators can always view (they need to manage the discussion)
    - Admins can always view
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Check participation gate (unless user is creator, admin, or demo discussion)
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)
    is_demo = discussion_id in _demo_discussion_ids()
    
    if not is_creator and not is_admin and not is_demo:
        vote_count, identifier_type = get_user_vote_count(discussion_id)
        votes_needed = max(0, PARTICIPATION_THRESHOLD - vote_count)
        
        if votes_needed > 0:
            # Show participation gate page
            return render_template('discussions/consensus_gate.html',
                                 discussion=discussion,
                                 vote_count=vote_count,
                                 votes_needed=votes_needed,
                                 threshold=PARTICIPATION_THRESHOLD)
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        # Check if ready for first analysis
        plan = get_consensus_execution_plan(discussion_id, db)
        can_analyze = plan.get('is_ready', False)
        ready_message = plan.get('message', 'Not ready')
        
        return render_template('discussions/consensus_not_ready.html',
                             discussion=discussion,
                             can_analyze=can_analyze,
                             message=ready_message,
                             consensus_thresholds=consensus_thresholds_dict())

    is_publishable, withheld_reason = _assess_analysis_publishability(analysis)
    if not is_publishable:
        return render_template(
            'discussions/consensus_not_ready.html',
            discussion=discussion,
            can_analyze=(is_creator or is_admin),
            message=withheld_reason,
            consensus_thresholds=consensus_thresholds_dict(),
        )
    
    # Ranked, published-visible statements. Query order is not the engine's
    # ranking, and deleted / rejected statements must not stay on the page.
    cluster_data = analysis.cluster_data or {}
    consensus_statements = _ranked_public_statements(cluster_data.get('consensus_statements'))
    bridge_statements = _ranked_public_statements(cluster_data.get('bridge_statements'))
    divisive_statements = _ranked_public_statements(cluster_data.get('divisive_statements'))
    
    # Build opinion groups — include ALL clusters, even those too small to have
    # representative statements, so users are never silently missing groups.
    cluster_assignments = cluster_data.get('cluster_assignments') or {}
    representative_data = cluster_data.get('representative_statements') or {}

    # ── Normalise representative_data keys to int/str once ────────────────────
    # JSON round-trips may produce string keys for numeric cluster IDs.
    # Doing this once here lets us use a simple dict.get() throughout.
    def _norm_cid(k):
        try:
            return int(k)
        except (ValueError, TypeError):
            return str(k)

    _rep_data: dict = {_norm_cid(k): v for k, v in representative_data.items()}

    # ── Collect ALL cluster IDs (representative_data + cluster_assignments) ───
    all_cluster_ids: set = set(_rep_data.keys())
    for c in cluster_assignments.values():
        all_cluster_ids.add(_norm_cid(c))

    # ── Batch-fetch representative Statement objects (single DB round-trip) ───
    # Filtered to published-visible here, not only where the group cards are
    # built: this map also seeds the PCA axis labels, and a deleted or
    # rejected statement was still reaching the chart through that path.
    all_rep_stmt_ids = {
        sid
        for stmts in _rep_data.values()
        for sid in (_safe_statement_id(s) for s in stmts)
        if sid is not None
    }
    rep_statements_map: dict = {}
    if all_rep_stmt_ids:
        rep_statements_map = {
            stmt.id: stmt
            for stmt in Statement.query.filter(Statement.id.in_(all_rep_stmt_ids)).all()
            if _statement_is_public(stmt)
        }

    def _sort_cid(x):
        try:
            return (0, int(x))
        except (ValueError, TypeError):
            return (1, str(x))

    opinion_groups = []
    for cluster_id in sorted(all_cluster_ids, key=_sort_cid):
        target_cluster = _norm_cid(cluster_id)

        # Human-readable name: integer cluster IDs are 0-indexed internally
        if isinstance(target_cluster, int):
            group_name = f"Group {target_cluster + 1}"
            participant_count = sum(
                1 for c in cluster_assignments.values()
                if _norm_cid(c) == target_cluster
            )
        else:
            group_name = target_cluster.title()
            participant_count = sum(
                1 for c in cluster_assignments.values()
                if str(c) == target_cluster
            )

        # ── Build enriched statement list ────────────────────────────────────
        # New (post-rigour-pass) fields: wilson_low/high, lift, p_value,
        # significant, out_agreement_rate, tested_direction. All have safe
        # fallbacks for analyses written by older versions of the engine.
        group_stmts = []
        for stmt_data in _rep_data.get(target_cluster, []):
            sid = _safe_statement_id(stmt_data)
            stmt = rep_statements_map.get(sid) if sid is not None else None
            if not _statement_is_public(stmt):
                continue
            agree_count = stmt_data.get('agree_count', 0)
            vote_count = stmt_data.get('vote_count', 0)
            agreement_rate = stmt_data.get('agreement_rate', 0)
            # Older analyses pre-dating the dead-zone classifier use a 0.5
            # cutoff. Keep that fallback so historical views don't flip.
            fallback_direction = 'agree' if agreement_rate >= 0.5 else 'reject'
            group_stmts.append({
                'statement_id': stmt.id,
                'content': stmt.content,
                'agreement_rate': agreement_rate,
                'wilson_low': stmt_data.get('wilson_low'),
                'wilson_high': stmt_data.get('wilson_high'),
                'vote_count': vote_count,
                'agree_count': agree_count,
                'disagree_count': stmt_data.get('disagree_count', vote_count - agree_count),
                'out_agreement_rate': stmt_data.get('out_agreement_rate'),
                'lift': stmt_data.get('lift'),
                'p_value': stmt_data.get('p_value'),
                'significant': stmt_data.get('significant'),
                'direction': stmt_data.get('direction', fallback_direction),
                'tested_direction': stmt_data.get('tested_direction', fallback_direction),
                'strength': stmt_data.get('strength', 0),
            })

        # Split into agreement / rejection / mixed buckets. Mixed (dead-zone)
        # statements are surfaced separately because a 49%–60% agreement
        # rate is not a defining belief of the group.
        agree_statements = [s for s in group_stmts if s['direction'] == 'agree']
        reject_statements = [s for s in group_stmts if s['direction'] == 'reject']
        mixed_statements = [s for s in group_stmts if s['direction'] == 'mixed']

        opinion_groups.append({
            'id': target_cluster,
            'name': group_name,
            'participant_count': participant_count,
            'statements': group_stmts,
            'agree_statements': agree_statements,
            'reject_statements': reject_statements,
            'mixed_statements': mixed_statements,
            # True when no representative statements could be surfaced.
            # Common for small groups or groups whose members voted on
            # different subsets of statements.  Re-running analysis after
            # more votes arrive will fill this in.
            'too_few_votes': len(group_stmts) == 0,
            # Flag for low statistical reliability — shown as a caution badge.
            'small_sample': participant_count < 5,
            # True if at least one representative statement is FDR-significant.
            'has_significant_signal': any(s.get('significant') for s in group_stmts),
        })

    drift = detect_analysis_drift(discussion, analysis)
    current_stmt_count = drift['current_stmt_count']
    analysed_stmt_count = drift['analysed_stmt_count']
    current_participant_count = drift['current_participant_count']
    analysed_participants = drift['analysed_participants']
    is_stale_analysis = drift['is_stale']

    # ── PCA axis labels from top loadings ─────────────────────────────────
    # The engine stores top-loading statement IDs per axis. Resolve the
    # statement content so the chart can display "← Agrees: 'X' │ 'Y' →"
    # instead of a bare "Principal Component 1". Re-use already-fetched
    # Statement objects and only issue a DB query for the residual.
    axis_loadings = cluster_data.get('pca_axis_loadings') or {}
    axis_loading_stmts_map = {
        s.id: s
        for s in (
            list(rep_statements_map.values())
            + list(consensus_statements)
            + list(bridge_statements)
            + list(divisive_statements)
        )
    }
    needed_ids = set()
    for axis in axis_loadings.values():
        for key in ('positive_statement_ids', 'negative_statement_ids'):
            needed_ids.update(axis.get(key, []) or [])
    missing_ids = needed_ids - axis_loading_stmts_map.keys()
    if missing_ids:
        for stmt in Statement.query.filter(Statement.id.in_(missing_ids)).all():
            if _statement_is_public(stmt):
                axis_loading_stmts_map[stmt.id] = stmt

    # ── "You are here": keys that the scatter-plot JS uses to highlight the viewer's dot.
    # Matches build_vote_matrix's participant ids (u_{id} for auth, a_{fp16} for anon).
    # Multiple anonymous aliases can yield multiple keys (legacy cookies / embed).
    viewer_participant_keys: list[str] = []
    if current_user.is_authenticated:
        viewer_participant_keys = [f"u_{current_user.id}"]
    else:
        try:
            seen_dot_keys: set[str] = set()
            for fp in anonymous_fingerprint_aliases_for_daily_lookup():
                key = f"a_{fp[:16]}"
                if key not in seen_dot_keys:
                    seen_dot_keys.add(key)
                    viewer_participant_keys.append(key)
        except Exception:
            pass

    # Track consensus view from partner context
    ref = request.args.get('ref')
    if ref:
        try:
            from app.api.utils import track_partner_event
            track_partner_event('partner_consensus_view', {
                'discussion_id': discussion.id,
                'discussion_title': discussion.title,
                'has_analysis': True,
                'num_clusters': analysis.num_clusters if analysis else 0,
                'participants_count': analysis.participants_count if analysis else 0
            })
        except Exception as e:
            current_app.logger.debug(f"Consensus tracking error: {e}")

    from app.lib.locale_utils import language_preference_cookie_params

    # Reuse already-fetched Statement objects — no extra DB round-trip.
    # Axis-only statements are included so chart labels translate too.
    translation_map, discussion_translation, view_lang, translation_incomplete = (
        _published_translations(
            discussion,
            list(consensus_statements)
            + list(bridge_statements)
            + list(divisive_statements)
            + list(rep_statements_map.values())
            + list(axis_loading_stmts_map.values()),
        )
    )
    axis_loading_map = _axis_loading_entries(axis_loading_stmts_map, translation_map)

    # Build lookups so the template can render CI + lift + out-group rate
    # on consensus / bridge / divisive statement cards (previously only
    # carried raw vote counts).
    consensus_data_by_id = _metrics_by_statement_id(cluster_data.get('consensus_statements'))
    bridge_data_by_id = _metrics_by_statement_id(cluster_data.get('bridge_statements'))
    divisive_data_by_id = _metrics_by_statement_id(cluster_data.get('divisive_statements'))

    resp = make_response(render_template(
        'discussions/consensus_results.html',
        discussion=discussion,
        analysis=analysis,
        consensus_statements=consensus_statements,
        bridge_statements=bridge_statements,
        divisive_statements=divisive_statements,
        consensus_data_by_id=consensus_data_by_id,
        bridge_data_by_id=bridge_data_by_id,
        divisive_data_by_id=divisive_data_by_id,
        opinion_groups=opinion_groups,
        translation_map=translation_map,
        discussion_translation=discussion_translation,
        translation_incomplete=translation_incomplete,
        current_lang=view_lang,
        axis_loadings=axis_loadings,
        axis_loading_map=axis_loading_map,
        viewer_participant_keys=viewer_participant_keys,
        is_stale_analysis=is_stale_analysis,
        current_stmt_count=current_stmt_count,
        analysed_stmt_count=analysed_stmt_count,
        current_participant_count=current_participant_count,
        analysed_participants=analysed_participants,
    ))
    if view_lang != 'en':
        resp.set_cookie('ss_lang', view_lang, **language_preference_cookie_params())
    return resp


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/data')
def get_cluster_data(discussion_id):
    """
    API endpoint to get cluster data for visualization
    Returns JSON with user positions and cluster assignments
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': _('No analysis available')}), 404

    is_publishable, withheld_reason = _assess_analysis_publishability(analysis)
    if not is_publishable:
        return jsonify({
            'error': 'analysis_withheld',
            'message': withheld_reason,
        }), 409

    # Return cluster data
    return jsonify({
        'cluster_assignments': analysis.cluster_data.get('cluster_assignments', {}),
        'pca_coordinates': analysis.cluster_data.get('pca_coordinates', {}),
        'metadata': analysis.cluster_data.get('metadata', {})
    })


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/statements')
def get_special_statements(discussion_id):
    """
    API endpoint to get consensus, bridge, and divisive statements
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': _('No analysis available')}), 404

    is_publishable, withheld_reason = _assess_analysis_publishability(analysis)
    if not is_publishable:
        return jsonify({
            'error': 'analysis_withheld',
            'message': withheld_reason,
        }), 409
    
    return jsonify({
        'consensus': analysis.cluster_data.get('consensus_statements', []),
        'bridge': analysis.cluster_data.get('bridge_statements', []),
        'divisive': analysis.cluster_data.get('divisive_statements', [])
    })


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/status')
def get_analysis_status(discussion_id):
    """
    API endpoint to check if analysis is ready or available
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Check if ready
    plan = get_consensus_execution_plan(discussion_id, db)
    
    # Get latest analysis if exists
    latest_analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    publishable = False
    withheld_reason = None
    if latest_analysis:
        publishable, withheld_reason = _assess_analysis_publishability(latest_analysis)

    response = {
        'can_analyze': plan.get('is_ready', False),
        'message': plan.get('message'),
        'analysis_mode': plan.get('mode'),
        'has_analysis': latest_analysis is not None,
        'analysis_publishable': publishable if latest_analysis else False,
        'analysis_withheld_reason': withheld_reason,
    }

    latest_job = ConsensusJob.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusJob.created_at.desc()).first()
    if latest_job:
        response['job'] = {
            'id': latest_job.id,
            'status': latest_job.status,
            'attempts': latest_job.attempts,
            'max_attempts': latest_job.max_attempts,
            'queued_at': latest_job.queued_at.isoformat() if latest_job.queued_at else None,
            'started_at': latest_job.started_at.isoformat() if latest_job.started_at else None,
            'completed_at': latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            'error_message': latest_job.error_message,
        }
    
    if latest_analysis:
        response['analysis'] = {
            'created_at': latest_analysis.created_at.isoformat(),
            'num_clusters': latest_analysis.num_clusters,
            'silhouette_score': latest_analysis.silhouette_score,
            'participants_count': latest_analysis.participants_count,
            'statements_count': latest_analysis.statements_count,
            'is_publishable': publishable,
            'withheld_reason': withheld_reason,
        }
    
    return jsonify(response)


@consensus_bp.route('/discussions/<int:discussion_id>/consensus/report')
def generate_report(discussion_id):
    """
    Generate a detailed PDF/HTML report of consensus analysis
    Includes cluster descriptions, key statements, and recommendations

    Participation Gate: Same as view_results - users must vote on at least
    PARTICIPATION_THRESHOLD statements before viewing.
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Check participation gate (same as view_results)
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)
    is_demo = discussion_id in _demo_discussion_ids()
    
    if not is_creator and not is_admin and not is_demo:
        vote_count, identifier_type = get_user_vote_count(discussion_id)
        votes_needed = max(0, PARTICIPATION_THRESHOLD - vote_count)
        
        if votes_needed > 0:
            # Redirect to gate page
            return render_template('discussions/consensus_gate.html',
                                 discussion=discussion,
                                 vote_count=vote_count,
                                 votes_needed=votes_needed,
                                 threshold=PARTICIPATION_THRESHOLD)
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash(_("No analysis available to generate report"), "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))

    is_publishable, withheld_reason = _assess_analysis_publishability(analysis)
    if not is_publishable:
        flash(withheld_reason, "warning")
        return redirect(url_for(
            'consensus.view_results',
            discussion_id=discussion.id,
            slug=discussion.slug,
        ))
    
    # Same ranking, visibility, and translation rules as the results page.
    cluster_data = analysis.cluster_data or {}
    consensus_statements = _ranked_public_statements(cluster_data.get('consensus_statements'))
    bridge_statements = _ranked_public_statements(cluster_data.get('bridge_statements'))
    divisive_statements = _ranked_public_statements(cluster_data.get('divisive_statements'))
    translation_map, discussion_translation, view_lang, translation_incomplete = (
        _published_translations(
            discussion,
            list(consensus_statements)
            + list(bridge_statements)
            + list(divisive_statements),
        )
    )

    resp = make_response(render_template(
        'discussions/consensus_report.html',
        discussion=discussion,
        analysis=analysis,
        consensus_statements=consensus_statements,
        bridge_statements=bridge_statements,
        divisive_statements=divisive_statements,
        consensus_data_by_id=_metrics_by_statement_id(cluster_data.get('consensus_statements')),
        bridge_data_by_id=_metrics_by_statement_id(cluster_data.get('bridge_statements')),
        divisive_data_by_id=_metrics_by_statement_id(cluster_data.get('divisive_statements')),
        translation_map=translation_map,
        discussion_translation=discussion_translation,
        translation_incomplete=translation_incomplete,
        current_lang=view_lang,
        for_print=request.args.get('print') == 'true',
    ))
    # Persist the language choice exactly as view_results does. Without this a
    # reader who arrives here with ?lang=fr is thrown back to English the
    # moment they follow "Back to Analysis".
    if view_lang != 'en':
        from app.lib.locale_utils import language_preference_cookie_params
        resp.set_cookie('ss_lang', view_lang, **language_preference_cookie_params())
    return resp


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/export')
def export_analysis(discussion_id):
    """
    Export consensus analysis data as JSON or CSV
    Useful for external analysis tools
    """
    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': _('No analysis available')}), 404

    is_publishable, withheld_reason = _assess_analysis_publishability(analysis)
    if not is_publishable:
        return jsonify({
            'error': 'analysis_withheld',
            'message': withheld_reason,
        }), 409

    export_format = request.args.get('format', 'json')
    
    if export_format == 'csv':
        import csv
        import io

        cluster_data = analysis.cluster_data or {}

        def _first_present(entry, *keys):
            """First key the entry actually carries — '' if none.

            A plain ``a or b`` chain discards legitimate 0.0 rates, which is
            exactly what a unanimously-rejected statement scores.
            """
            for key in keys:
                value = entry.get(key)
                if value is not None:
                    return value
            return ''

        def _excel_text(value):
            """Stop Excel treating statement text as a formula.

            The file is served with a UTF-8 BOM so Excel opens it. A cell
            starting with ``=``, ``+``, ``-``, ``@``, tab, or CR would run.
            """
            text = '' if value is None else str(value)
            if text[:1] in ('=', '+', '-', '@', '\t', '\r'):
                return "'" + text
            return text

        # Build a lookup: statement_id -> (classifications, metrics) from
        # cluster_data. A statement can legitimately be in more than one
        # section (consensus statements are usually bridges too), so labels
        # accumulate rather than overwrite — the previous dict assignment
        # silently dropped every earlier classification.
        classification_map = {}
        for label, stmts in (
            ('consensus', cluster_data.get('consensus_statements') or []),
            ('bridge',    cluster_data.get('bridge_statements') or []),
            ('divisive',  cluster_data.get('divisive_statements') or []),
        ):
            if not isinstance(stmts, list):
                continue
            for entry in stmts:
                sid = _safe_statement_id(entry)
                if sid is None:
                    continue
                # Normalise field names: bridge uses mean_agreement, divisive
                # uses agree_rate.
                metrics = {
                    'agreement_rate': _first_present(
                        entry, 'agreement_rate', 'mean_agreement', 'agree_rate'
                    ),
                    'wilson_low':       _first_present(entry, 'wilson_low'),
                    'wilson_high':      _first_present(entry, 'wilson_high'),
                    'gap_ci_low':       _first_present(entry, 'gap_ci_low', 'wilson_low'),
                    'gap_ci_high':      _first_present(entry, 'gap_ci_high', 'wilson_high'),
                    'p_value':          _first_present(entry, 'p_value'),
                    'p_value_gap':      _first_present(entry, 'p_value_gap'),
                    'chi2':             _first_present(entry, 'chi2'),
                    'significant':      _first_present(entry, 'significant'),
                    'group_gap':        _first_present(entry, 'group_gap'),
                    'polarity':         _first_present(entry, 'polarity'),
                    'strength':         _first_present(entry, 'strength'),
                    'analysed_vote_count': _first_present(entry, 'vote_count'),
                }
                existing = classification_map.get(sid)
                if existing is None:
                    classification_map[sid] = dict(
                        metrics, classification=label
                    )
                else:
                    existing['classification'] += f';{label}'
                    # Keep the first non-empty value for each metric so a
                    # later section cannot blank out an earlier one.
                    for key, value in metrics.items():
                        if existing.get(key) in ('', None):
                            existing[key] = value

        # Collect all statement IDs mentioned in the analysis
        all_stmt_ids = set(classification_map.keys())
        # Also include any that appear only in representative_statements
        representative = cluster_data.get('representative_statements') or {}
        if isinstance(representative, dict):
            for stmts in representative.values():
                if not isinstance(stmts, list):
                    continue
                for entry in stmts:
                    sid = _safe_statement_id(entry)
                    if sid is not None:
                        all_stmt_ids.add(sid)

        statements_by_id = {
            s.id: s
            for s in Statement.query.filter(Statement.id.in_(all_stmt_ids)).all()
        } if all_stmt_ids else {}

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'statement_id',
            'content',
            'classification',
            'polarity',
            'agree_count',
            'disagree_count',
            'unsure_count',
            'total_votes',
            'analysed_vote_count',
            'agreement_rate',
            'wilson_low',
            'wilson_high',
            'gap_ci_low_newcombe',
            'gap_ci_high_newcombe',
            'p_value_omnibus_permutation',
            'p_value_gap_fisher',
            'chi2_observed',
            'fdr_significant',
            'group_gap',
            'strength',
        ])

        for sid in sorted(all_stmt_ids):
            stmt = statements_by_id.get(sid)
            # Skip anything not publishable, and anything whose row is gone
            # (hard-deleted / purged): a row with blank content and empty
            # counts is worse than no row, and inconsistent with dropping
            # soft-deleted statements two lines up.
            if not _statement_is_public(stmt):
                continue
            meta = classification_map.get(sid, {})
            # Statement stores denormalised counters as vote_count_*; the old
            # `agree_count` / `disagree_count` attribute names do not exist,
            # so every row exported zeroes.
            agree = int(stmt.vote_count_agree or 0)
            disagree = int(stmt.vote_count_disagree or 0)
            unsure = int(stmt.vote_count_unsure or 0)
            total = agree + disagree + unsure
            writer.writerow([
                sid,
                _excel_text(stmt.content),
                meta.get('classification', 'unclassified'),
                meta.get('polarity', ''),
                agree,
                disagree,
                unsure,
                total,
                meta.get('analysed_vote_count', ''),
                meta.get('agreement_rate', ''),
                meta.get('wilson_low', ''),
                meta.get('wilson_high', ''),
                meta.get('gap_ci_low', ''),
                meta.get('gap_ci_high', ''),
                meta.get('p_value', ''),
                meta.get('p_value_gap', ''),
                meta.get('chi2', ''),
                meta.get('significant', ''),
                meta.get('group_gap', ''),
                meta.get('strength', ''),
            ])

        # UTF-8 BOM ensures Excel on Windows detects encoding correctly
        csv_bytes = b'\xef\xbb\xbf' + output.getvalue().encode('utf-8')
        safe_title = ''.join(c if c.isalnum() or c in ('-', '_') else '_' for c in discussion.title)
        filename = f"consensus_{discussion_id}_{safe_title[:40].strip('_')}.csv"

        from flask import Response
        return Response(
            csv_bytes,
            mimetype='text/csv',
            headers={'Content-Disposition': f'attachment; filename="{filename}"'},
        )

    # Return full JSON data
    return jsonify({
        'discussion_id': discussion_id,
        'discussion_title': discussion.title,
        'analysis_date': analysis.created_at.isoformat(),
        'data': analysis.cluster_data
    })


# =============================================================================
# PHASE 4: LLM SUMMARY ROUTES
# =============================================================================

@consensus_bp.route('/discussions/<int:discussion_id>/consensus/generate-summary', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def generate_summary(discussion_id):
    """
    Generate AI summary of consensus analysis
    Requires user to have an active API key
    """
    from app.lib.llm_utils import generate_discussion_summary

    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash(_("No consensus analysis available. Run analysis first."), "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if user has API key
    from app.models import UserAPIKey
    has_key = UserAPIKey.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).first() is not None
    
    if not has_key:
        flash(_("Please add an LLM API key in settings to use AI summary features"), "info")
        return redirect(url_for('api_keys.add_api_key'))
    
    # Get statement details
    consensus_stmts = analysis.cluster_data.get('consensus_statements', [])
    bridge_stmts = analysis.cluster_data.get('bridge_statements', [])
    divisive_stmts = analysis.cluster_data.get('divisive_statements', [])
    
    # Enrich with content
    for stmt_list in [consensus_stmts, bridge_stmts, divisive_stmts]:
        for stmt in stmt_list:
            statement = db.session.get(Statement, stmt['statement_id'])
            if statement:
                stmt['content'] = statement.content
    
    try:
        summary = generate_discussion_summary(
            discussion_id=discussion_id,
            consensus_statements=consensus_stmts,
            bridge_statements=bridge_stmts,
            divisive_statements=divisive_stmts,
            user_id=current_user.id,
            db=db
        )
        
        if summary:
            # Store summary in cluster_data
            analysis.cluster_data['ai_summary'] = summary
            analysis.cluster_data['summary_generated_at'] = utcnow_naive().isoformat()
            analysis.cluster_data['summary_generated_by'] = current_user.id
            db.session.commit()
            _invalidate_snapshot_cache(discussion_id)
            
            flash(_("AI summary generated successfully!"), "success")
        else:
            flash(_("Failed to generate summary. Check your API key status."), "danger")
    
    except Exception as e:
        logger.error(f"Error generating summary: {e}", exc_info=True)
        flash(_("An error occurred while generating summary"), "danger")
    
    return redirect(url_for('consensus.view_results', discussion_id=discussion_id))


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/summary')
def get_summary_api(discussion_id):
    """
    API endpoint to get AI-generated summary
    """
    discussion = db.get_or_404(Discussion, discussion_id)
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': _('No analysis available')}), 404
    
    summary = analysis.cluster_data.get('ai_summary')
    
    if not summary:
        return jsonify({'error': _('No summary generated yet')}), 404
    
    return jsonify({
        'summary': summary,
        'generated_at': analysis.cluster_data.get('summary_generated_at'),
        'generated_by': analysis.cluster_data.get('summary_generated_by')
    })


@consensus_bp.route('/discussions/<int:discussion_id>/consensus/generate-labels', methods=['POST'])
@login_required
@limiter.limit("5 per hour")
def generate_cluster_labels_route(discussion_id):
    """
    Generate AI labels for user clusters
    Requires user to have an active API key
    """
    from app.lib.llm_utils import generate_cluster_labels

    discussion = db.get_or_404(Discussion, discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash(_("No consensus analysis available. Run analysis first."), "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if user has API key
    from app.models import UserAPIKey
    has_key = UserAPIKey.query.filter_by(
        user_id=current_user.id,
        is_active=True
    ).first() is not None
    
    if not has_key:
        flash(_("Please add an LLM API key in settings to use AI labeling features"), "info")
        return redirect(url_for('api_keys.add_api_key'))
    
    # Get all statements for context
    statements = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    ).all()
    
    statement_dicts = [{'id': s.id, 'content': s.content} for s in statements]
    
    try:
        labels = generate_cluster_labels(
            cluster_data=analysis.cluster_data,
            statements=statement_dicts,
            user_id=current_user.id,
            db=db
        )

        if labels:
            # Grounding check: an LLM cluster label should cite at least
            # one statement id that actually appears in that cluster's
            # representative list. Unlabelled clusters are preferable to
            # confidently-wrong labels (e.g. an "Environmentalists" badge
            # on a group that clustered around housing).
            rep_by_cluster = analysis.cluster_data.get('representative_statements', {}) or {}
            def _rep_ids(cid_key):
                entries = rep_by_cluster.get(cid_key) or rep_by_cluster.get(str(cid_key)) or []
                return {int(e['statement_id']) for e in entries}

            grounded_labels = {}
            dropped = 0
            for cid_key, payload in (labels or {}).items():
                cited = set()
                if isinstance(payload, dict):
                    cited = {int(sid) for sid in (payload.get('supporting_statement_ids') or [])}
                rep_ids = _rep_ids(cid_key)
                if cited and cited & rep_ids:
                    grounded_labels[cid_key] = payload
                elif not cited:
                    # If the helper didn't produce citations, keep the
                    # label but mark it as unverified so the template can
                    # style it differently.
                    if isinstance(payload, dict):
                        payload = {**payload, 'unverified': True}
                    grounded_labels[cid_key] = payload
                else:
                    dropped += 1

            analysis.cluster_data['cluster_labels'] = grounded_labels
            analysis.cluster_data['labels_generated_at'] = utcnow_naive().isoformat()
            analysis.cluster_data['labels_dropped_for_grounding'] = dropped
            db.session.commit()
            _invalidate_snapshot_cache(discussion_id)

            if dropped:
                flash(_("Cluster labels generated. %(n)d label(s) were withheld because the model could not cite supporting statements.", n=dropped), "info")
            else:
                flash(_("Cluster labels generated successfully!"), "success")
        else:
            flash(_("Failed to generate labels. Check your API key status."), "danger")
    
    except Exception as e:
        logger.error(f"Error generating labels: {e}", exc_info=True)
        flash(_("An error occurred while generating labels"), "danger")
    
    return redirect(url_for('consensus.view_results', discussion_id=discussion_id))

