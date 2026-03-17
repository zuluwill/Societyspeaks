# app/discussions/consensus.py
"""
Consensus & Clustering API Routes (Phase 3)

Provides endpoints for running consensus analysis and viewing results
"""
from flask import abort, render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
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

consensus_bp = Blueprint('consensus', __name__)
logger = logging.getLogger(__name__)

# Minimum votes required to unlock consensus analysis
PARTICIPATION_THRESHOLD = CONSENSUS_VIEW_RESULTS_MIN_VOTES

DEMO_DISCUSSION_IDS = {25}


def _oversize_publishability_thresholds():
    """Centralized publication thresholds for oversize analyses."""
    return {
        'min_stability_runs': int(current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_RUNS', 3)),
        'min_stability_mean_ari': float(current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_ARI', 0.30)),
    }


def _assess_analysis_publishability(analysis):
    """
    Determine whether analysis should be published to end users.

    In oversize mode, require minimum stability to avoid publishing
    potentially unstable cluster structures.
    """
    metadata = (analysis.cluster_data or {}).get('metadata', {})
    if not metadata.get('oversize_mode'):
        return True, None

    thresholds = _oversize_publishability_thresholds()
    runs = int(metadata.get('stability_runs', 0) or 0)
    mean_ari_raw = metadata.get('stability_mean_ari')
    try:
        mean_ari = float(mean_ari_raw)
    except (TypeError, ValueError):
        mean_ari = 0.0

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
          - is_consensus_unlocked
          - consensus_progress
    """
    from sqlalchemy import func
    from app.api.utils import get_discussion_participant_count

    thresholds = consensus_thresholds_dict()
    user_vote_count, _ = get_user_vote_count(discussion.id)
    participation_threshold = PARTICIPATION_THRESHOLD
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id

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
        'is_consensus_unlocked': bool(is_creator or user_vote_count >= participation_threshold),
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
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Only discussion owner can trigger analysis
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can run consensus analysis", "danger")
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
            flash("Consensus analysis queued. Results will appear once processing completes.", "success")
        else:
            flash(message or "Analysis is already queued for this discussion.", "info")
        return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
    except Exception as e:
        logger.error(f"Error queueing consensus analysis: {e}", exc_info=True)
        flash("An error occurred while queueing analysis. Please try again later.", "danger")
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
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Check participation gate (unless user is creator, admin, or demo discussion)
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)
    is_demo = discussion_id in DEMO_DISCUSSION_IDS
    
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
    
    # Get representative statements per opinion group
    # This shows what each group believes (top 5 statements they agree on)
    representative_data = analysis.cluster_data.get('representative_statements', {})
    opinion_groups = []
    
    if representative_data:
        # Collect all statement IDs across all groups
        all_rep_stmt_ids = []
        for cluster_id, stmts in representative_data.items():
            all_rep_stmt_ids.extend([s['statement_id'] for s in stmts])
        
        # Fetch all statements in one query for efficiency
        rep_statements_map = {}
        if all_rep_stmt_ids:
            rep_statements = Statement.query.filter(Statement.id.in_(all_rep_stmt_ids)).all()
            rep_statements_map = {s.id: s for s in rep_statements}
        
        # Build opinion groups with enriched statement data
        # Handle non-numeric cluster IDs gracefully (e.g., "noise" clusters)
        def safe_cluster_sort_key(x):
            try:
                return (0, int(x))
            except (ValueError, TypeError):
                return (1, str(x))
        
        for cluster_id in sorted(representative_data.keys(), key=safe_cluster_sort_key):
            group_stmts = []
            for stmt_data in representative_data[cluster_id]:
                stmt = rep_statements_map.get(stmt_data['statement_id'])
                if stmt:
                    group_stmts.append({
                        'content': stmt.content,
                        'agreement_rate': stmt_data.get('agreement_rate', 0),
                        'vote_count': stmt_data.get('vote_count', 0),
                        'strength': stmt_data.get('strength', 0)
                    })
            
            if group_stmts:
                # Count participants in this cluster
                # Normalize comparison: cluster_id from representative_data and values from cluster_assignments
                # may be strings or ints depending on JSON serialization
                cluster_assignments = analysis.cluster_data.get('cluster_assignments', {})
                
                # Handle non-numeric cluster IDs (e.g., "noise")
                try:
                    target_cluster = int(cluster_id)
                    group_name = f"Group {target_cluster + 1}"
                except (ValueError, TypeError):
                    target_cluster = str(cluster_id)
                    group_name = str(cluster_id).title()  # e.g., "noise" -> "Noise"
                
                # Safe comparison that handles both numeric and string cluster IDs
                def matches_cluster(c):
                    try:
                        return int(c) == target_cluster if isinstance(target_cluster, int) else str(c) == target_cluster
                    except (ValueError, TypeError):
                        return str(c) == str(target_cluster)
                
                participant_count = sum(1 for c in cluster_assignments.values() if matches_cluster(c))
                
                opinion_groups.append({
                    'id': target_cluster,
                    'name': group_name,
                    'participant_count': participant_count,
                    'statements': group_stmts
                })

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

    return render_template('discussions/consensus_results.html',
                         discussion=discussion,
                         analysis=analysis,
                         consensus_statements=consensus_statements,
                         bridge_statements=bridge_statements,
                         divisive_statements=divisive_statements,
                         opinion_groups=opinion_groups)


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/data')
def get_cluster_data(discussion_id):
    """
    API endpoint to get cluster data for visualization
    Returns JSON with user positions and cluster assignments
    """
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404

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
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404

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
    discussion = Discussion.query.get_or_404(discussion_id)

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
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Check participation gate (same as view_results)
    is_creator = current_user.is_authenticated and current_user.id == discussion.creator_id
    is_admin = current_user.is_authenticated and getattr(current_user, 'is_admin', False)
    is_demo = discussion_id in DEMO_DISCUSSION_IDS
    
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
        flash("No analysis available to generate report", "warning")
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
    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404

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
                        'classification': label,
                        'agreement_rate': agreement_rate,
                        'strength':       entry.get('strength', ''),
                        'vote_count':     entry.get('vote_count', ''),
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
            'agree_count',
            'disagree_count',
            'total_votes',
            'agreement_rate',
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
                agree,
                disagree,
                total,
                meta.get('agreement_rate', ''),
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

    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash("No consensus analysis available. Run analysis first.", "warning")
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
        flash("Please add an LLM API key in settings to use AI summary features", "info")
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
            
            flash("AI summary generated successfully!", "success")
        else:
            flash("Failed to generate summary. Check your API key status.", "danger")
    
    except Exception as e:
        logger.error(f"Error generating summary: {e}", exc_info=True)
        flash("An error occurred while generating summary", "danger")
    
    return redirect(url_for('consensus.view_results', discussion_id=discussion_id))


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/summary')
def get_summary_api(discussion_id):
    """
    API endpoint to get AI-generated summary
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        return jsonify({'error': 'forbidden'}), 403

    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404
    
    summary = analysis.cluster_data.get('ai_summary')
    
    if not summary:
        return jsonify({'error': 'No summary generated yet'}), 404
    
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

    discussion = Discussion.query.get_or_404(discussion_id)

    if discussion.programme and not can_view_programme(discussion.programme, current_user):
        abort(403)

    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash("No consensus analysis available. Run analysis first.", "warning")
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
        flash("Please add an LLM API key in settings to use AI labeling features", "info")
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
            # Store labels in cluster_data
            analysis.cluster_data['cluster_labels'] = labels
            analysis.cluster_data['labels_generated_at'] = utcnow_naive().isoformat()
            db.session.commit()
            _invalidate_snapshot_cache(discussion_id)
            
            flash("Cluster labels generated successfully!", "success")
        else:
            flash("Failed to generate labels. Check your API key status.", "danger")
    
    except Exception as e:
        logger.error(f"Error generating labels: {e}", exc_info=True)
        flash("An error occurred while generating labels", "danger")
    
    return redirect(url_for('consensus.view_results', discussion_id=discussion_id))

