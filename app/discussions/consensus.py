# app/discussions/consensus.py
"""
Consensus & Clustering API Routes (Phase 3)

Provides endpoints for running consensus analysis and viewing results
"""
from flask import abort, render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app, make_response
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Discussion, ConsensusAnalysis, ConsensusJob, Statement, StatementVote
from app.discussions.statements import get_statement_vote_fingerprint
from app.lib.consensus_engine import can_cluster, get_consensus_execution_plan
from app.discussions.jobs import enqueue_consensus_job
from app.discussions.thresholds import consensus_thresholds_dict, CONSENSUS_VIEW_RESULTS_MIN_VOTES
from app.programmes.permissions import can_view_programme
from datetime import datetime, timedelta
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
    Only counts votes on non-deleted statements (aligned with consensus analysis).
    
    For authenticated users, also counts any votes made before login 
    (via session fingerprint) to ensure votes persist across login.
    
    Returns: (vote_count, identifier_type)
        - vote_count: number of distinct (non-deleted) statements voted on
        - identifier_type: 'user' or 'anonymous'
    """
    # Only count votes on non-deleted statements (same as consensus analysis)
    if current_user.is_authenticated:
        # Count distinct statements voted on (avoid double-count if user had both anon and user votes before merge)
        user_stmt_ids = [
            r[0] for r in StatementVote.query.filter_by(
                discussion_id=discussion_id,
                user_id=current_user.id
            ).join(Statement, StatementVote.statement_id == Statement.id).filter(
                Statement.is_deleted.is_(False)
            ).with_entities(StatementVote.statement_id).distinct().all()
        ]
        user_set = set(user_stmt_ids)
        try:
            fingerprint = get_statement_vote_fingerprint()
            if fingerprint:
                anon_stmt_ids = [
                    r[0] for r in StatementVote.query.filter_by(
                        discussion_id=discussion_id,
                        session_fingerprint=fingerprint
                    ).filter(StatementVote.user_id.is_(None)).join(
                        Statement, StatementVote.statement_id == Statement.id
                    ).filter(Statement.is_deleted.is_(False)).with_entities(
                        StatementVote.statement_id
                    ).distinct().all()
                ]
                user_set = user_set | set(anon_stmt_ids)
        except Exception as e:
            logger.debug(f"Could not get fingerprint for auth user: {e}")
        return len(user_set), 'user'
    else:
        try:
            fingerprint = get_statement_vote_fingerprint()
            if fingerprint:
                anon_stmt_ids = [
                    r[0] for r in StatementVote.query.filter_by(
                        discussion_id=discussion_id,
                        session_fingerprint=fingerprint
                    ).join(Statement, StatementVote.statement_id == Statement.id).filter(
                        Statement.is_deleted.is_(False)
                    ).with_entities(StatementVote.statement_id).distinct().all()
                ]
                return len(anon_stmt_ids), 'anonymous'
        except Exception as e:
            logger.debug(f"Could not get fingerprint: {e}")
        return 0, 'anonymous'


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
    from sqlalchemy import func
    from app.api.utils import get_discussion_participant_count

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
            'recommended_statements': int(thresholds.get('recommended_statements', 7)),
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
    
    # Get statement details for consensus/bridge/divisive
    consensus_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('consensus_statements', [])]
    bridge_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('bridge_statements', [])]
    divisive_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('divisive_statements', [])]
    
    consensus_statements = Statement.query.filter(Statement.id.in_(consensus_stmt_ids)).all() if consensus_stmt_ids else []
    bridge_statements = Statement.query.filter(Statement.id.in_(bridge_stmt_ids)).all() if bridge_stmt_ids else []
    divisive_statements = Statement.query.filter(Statement.id.in_(divisive_stmt_ids)).all() if divisive_stmt_ids else []
    
    # Build opinion groups — include ALL clusters, even those too small to have
    # representative statements, so users are never silently missing groups.
    cluster_assignments = analysis.cluster_data.get('cluster_assignments', {})
    representative_data = analysis.cluster_data.get('representative_statements', {})

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
    all_rep_stmt_ids = [s['statement_id'] for stmts in _rep_data.values() for s in stmts]
    rep_statements_map: dict = {}
    if all_rep_stmt_ids:
        rep_stmts = Statement.query.filter(Statement.id.in_(all_rep_stmt_ids)).all()
        rep_statements_map = {s.id: s for s in rep_stmts}

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
            stmt = rep_statements_map.get(stmt_data['statement_id'])
            if not stmt:
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

    # ── Stale-analysis detection ──────────────────────────────────────────
    # If votes arrived after the analysis was stored, let the viewer know
    # a re-run would refresh the picture. Thresholds chosen to avoid
    # nagging when the drift is small.
    from sqlalchemy import func
    current_stmt_count = Statement.query.filter_by(
        discussion_id=discussion.id, is_deleted=False
    ).count()
    current_vote_total = db.session.query(
        func.coalesce(
            func.sum(Statement.vote_count_agree) + func.sum(Statement.vote_count_disagree) + func.sum(Statement.vote_count_unsure),
            0,
        )
    ).filter(Statement.discussion_id == discussion.id, Statement.is_deleted.is_(False)).scalar() or 0
    analysed_stmt_count = int(analysis.statements_count or 0)
    analysed_participants = int(analysis.participants_count or 0)
    stmt_drift = current_stmt_count - analysed_stmt_count
    # 10% participant drift or any new statement triggers the notice.
    is_stale_analysis = (
        stmt_drift > 0
        or (analysed_participants > 0 and current_vote_total > 0
            and current_vote_total >= int(analysed_participants * 1.1))
    )

    # ── PCA axis labels from top loadings ─────────────────────────────────
    # The engine stores top-loading statement IDs per axis. Resolve the
    # statement content so the chart can display "← Agrees: 'X' │ 'Y' →"
    # instead of a bare "Principal Component 1". Re-use already-fetched
    # Statement objects and only issue a DB query for the residual.
    axis_loadings = analysis.cluster_data.get('pca_axis_loadings', {}) or {}
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
            axis_loading_stmts_map[stmt.id] = stmt

    # ── "You are here": key that the scatter-plot JS uses to highlight
    # the viewing participant's own dot. Matches build_vote_matrix's
    # identifier convention (u_{id} for auth, a_{fp16} for anon).
    viewer_participant_key = None
    if current_user.is_authenticated:
        viewer_participant_key = f"u_{current_user.id}"
    else:
        try:
            from app.discussions.statements import get_statement_vote_fingerprint
            fp = get_statement_vote_fingerprint()
            if fp:
                viewer_participant_key = f"a_{fp[:16]}"
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
    from app.lib.translation import (
        get_cached_discussion_translation,
        get_cached_statement_translations,
        resolve_language,
    )

    view_lang = resolve_language(request)
    # Reuse already-fetched Statement objects — no extra DB round-trip needed.
    # consensus/bridge/divisive are lists of ORM objects; rep_statements_map
    # holds the objects for representative statements.
    _all_for_i18n = (
        list(consensus_statements)
        + list(bridge_statements)
        + list(divisive_statements)
        + list(rep_statements_map.values())
    )
    translation_map = (
        get_cached_statement_translations(_all_for_i18n, view_lang)
        if view_lang != 'en' and _all_for_i18n
        else {}
    )
    discussion_translation = (
        get_cached_discussion_translation(discussion, view_lang)
        if view_lang != 'en'
        else None
    )

    # Build a simple id → statement-ish dict for axis labels (template
    # needs both the statement object and the raw content for truncation).
    axis_loading_map = {
        sid: {
            'statement_id': sid,
            'content': stmt.content,
            'short': (stmt.content[:80] + '…') if len(stmt.content) > 80 else stmt.content,
        }
        for sid, stmt in axis_loading_stmts_map.items()
    }

    # Build lookups so the template can render CI + lift + out-group rate
    # on consensus / bridge / divisive statement cards (previously only
    # carried raw vote counts).
    consensus_data_by_id = {
        int(s['statement_id']): s
        for s in (analysis.cluster_data.get('consensus_statements') or [])
    }
    bridge_data_by_id = {
        int(s['statement_id']): s
        for s in (analysis.cluster_data.get('bridge_statements') or [])
    }
    divisive_data_by_id = {
        int(s['statement_id']): s
        for s in (analysis.cluster_data.get('divisive_statements') or [])
    }

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
        current_lang=view_lang,
        axis_loadings=axis_loadings,
        axis_loading_map=axis_loading_map,
        viewer_participant_key=viewer_participant_key,
        is_stale_analysis=is_stale_analysis,
        current_stmt_count=current_stmt_count,
        analysed_stmt_count=analysed_stmt_count,
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
    
    # Get all statement details
    consensus_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('consensus_statements', [])]
    bridge_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('bridge_statements', [])]
    divisive_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('divisive_statements', [])]
    
    consensus_statements = Statement.query.filter(Statement.id.in_(consensus_stmt_ids)).all() if consensus_stmt_ids else []
    bridge_statements = Statement.query.filter(Statement.id.in_(bridge_stmt_ids)).all() if bridge_stmt_ids else []
    divisive_statements = Statement.query.filter(Statement.id.in_(divisive_stmt_ids)).all() if divisive_stmt_ids else []
    
    # Render report template (can be configured for PDF export)
    return render_template('discussions/consensus_report.html',
                         discussion=discussion,
                         analysis=analysis,
                         consensus_statements=consensus_statements,
                         bridge_statements=bridge_statements,
                         divisive_statements=divisive_statements,
                         for_print=request.args.get('print') == 'true')


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

        # Build a lookup: statement_id -> (classification, metrics) from cluster_data
        classification_map = {}
        for label, stmts in (
            ('consensus', cluster_data.get('consensus_statements', [])),
            ('bridge',    cluster_data.get('bridge_statements', [])),
            ('divisive',  cluster_data.get('divisive_statements', [])),
        ):
            for entry in stmts:
                sid = entry.get('statement_id')
                if sid is not None:
                    # Normalise field names: bridge uses mean_agreement, divisive uses agree_rate
                    agreement_rate = (
                        entry.get('agreement_rate')
                        or entry.get('mean_agreement')
                        or entry.get('agree_rate')
                        or ''
                    )
                    classification_map[sid] = {
                        'classification':   label,
                        'agreement_rate':   agreement_rate,
                        'wilson_low':       entry.get('wilson_low', ''),
                        'wilson_high':      entry.get('wilson_high', ''),
                        'gap_ci_low':       entry.get('gap_ci_low', entry.get('wilson_low', '')),
                        'gap_ci_high':      entry.get('gap_ci_high', entry.get('wilson_high', '')),
                        'p_value':          entry.get('p_value', ''),
                        'p_value_gap':      entry.get('p_value_gap', ''),
                        'chi2':             entry.get('chi2', ''),
                        'significant':      entry.get('significant', ''),
                        'group_gap':        entry.get('group_gap', ''),
                        'polarity':         entry.get('polarity', ''),
                        'strength':         entry.get('strength', ''),
                        'vote_count':       entry.get('vote_count', ''),
                    }

        # Collect all statement IDs mentioned in the analysis
        all_stmt_ids = set(classification_map.keys())
        # Also include any that appear only in representative_statements
        for stmts in cluster_data.get('representative_statements', {}).values():
            for entry in stmts:
                sid = entry.get('statement_id')
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
            'total_votes',
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
            meta = classification_map.get(sid, {})
            agree   = getattr(stmt, 'agree_count',    0) if stmt else ''
            disagree = getattr(stmt, 'disagree_count', 0) if stmt else ''
            total   = (agree + disagree) if isinstance(agree, int) and isinstance(disagree, int) else ''
            writer.writerow([
                sid,
                stmt.content if stmt else '',
                meta.get('classification', 'unclassified'),
                meta.get('polarity', ''),
                agree,
                disagree,
                total,
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

