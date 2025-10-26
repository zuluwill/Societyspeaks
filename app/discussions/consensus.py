# app/discussions/consensus.py
"""
Consensus & Clustering API Routes (Phase 3)

Provides endpoints for running consensus analysis and viewing results
"""
from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Discussion, ConsensusAnalysis, Statement
from app.lib.consensus_engine import run_consensus_analysis, save_consensus_analysis, can_cluster
from datetime import datetime, timedelta
import logging

consensus_bp = Blueprint('consensus', __name__)
logger = logging.getLogger(__name__)


@consensus_bp.route('/discussions/<int:discussion_id>/consensus/analyze', methods=['POST'])
@login_required
@limiter.limit("3 per hour")
def trigger_analysis(discussion_id):
    """
    Trigger consensus analysis for a discussion
    Rate limited to prevent abuse (computationally expensive)
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Only discussion owner can trigger analysis
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can run consensus analysis", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if ready for clustering
    ready, message = can_cluster(discussion_id, db)
    if not ready:
        flash(f"Cannot run analysis: {message}", "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
    # Check if recent analysis exists (avoid re-running too frequently)
    recent_analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if recent_analysis:
        time_since_last = datetime.utcnow() - recent_analysis.created_at
        if time_since_last < timedelta(hours=1):
            flash(f"Analysis was run {int(time_since_last.total_seconds() / 60)} minutes ago. Please wait before running again.", "info")
            return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
    
    try:
        # Run analysis
        logger.info(f"Starting consensus analysis for discussion {discussion_id}")
        results = run_consensus_analysis(discussion_id, db, method='agglomerative')
        
        if results is None:
            flash("Unable to perform analysis with current data", "danger")
            return redirect(url_for('discussions.view_discussion', 
                                  discussion_id=discussion.id,
                                  slug=discussion.slug))
        
        # Save results
        analysis = save_consensus_analysis(discussion_id, results, db)
        
        flash(f"Consensus analysis complete! Found {results['metadata']['num_clusters']} opinion groups", "success")
        return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
        
    except Exception as e:
        logger.error(f"Error running consensus analysis: {e}", exc_info=True)
        flash("An error occurred during analysis. Please try again later.", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))


@consensus_bp.route('/discussions/<int:discussion_id>/consensus')
def view_results(discussion_id):
    """
    View consensus analysis results page
    Shows clusters, consensus statements, bridges, and divisive points
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        # Check if ready for first analysis
        ready, message = can_cluster(discussion_id, db)
        can_analyze = ready
        ready_message = message
        
        return render_template('discussions/consensus_not_ready.html',
                             discussion=discussion,
                             can_analyze=can_analyze,
                             message=ready_message)
    
    # Get statement details for consensus/bridge/divisive
    consensus_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('consensus_statements', [])]
    bridge_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('bridge_statements', [])]
    divisive_stmt_ids = [s['statement_id'] for s in analysis.cluster_data.get('divisive_statements', [])]
    
    consensus_statements = Statement.query.filter(Statement.id.in_(consensus_stmt_ids)).all() if consensus_stmt_ids else []
    bridge_statements = Statement.query.filter(Statement.id.in_(bridge_stmt_ids)).all() if bridge_stmt_ids else []
    divisive_statements = Statement.query.filter(Statement.id.in_(divisive_stmt_ids)).all() if divisive_stmt_ids else []
    
    return render_template('discussions/consensus_results.html',
                         discussion=discussion,
                         analysis=analysis,
                         consensus_statements=consensus_statements,
                         bridge_statements=bridge_statements,
                         divisive_statements=divisive_statements)


@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/data')
def get_cluster_data(discussion_id):
    """
    API endpoint to get cluster data for visualization
    Returns JSON with user positions and cluster assignments
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404
    
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
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404
    
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
    
    # Check if ready
    ready, message = can_cluster(discussion_id, db)
    
    # Get latest analysis if exists
    latest_analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    response = {
        'can_analyze': ready,
        'message': message,
        'has_analysis': latest_analysis is not None
    }
    
    if latest_analysis:
        response['analysis'] = {
            'created_at': latest_analysis.created_at.isoformat(),
            'num_clusters': latest_analysis.num_clusters,
            'silhouette_score': latest_analysis.silhouette_score,
            'participants_count': latest_analysis.participants_count,
            'statements_count': latest_analysis.statements_count
        }
    
    return jsonify(response)


@consensus_bp.route('/discussions/<int:discussion_id>/consensus/report')
def generate_report(discussion_id):
    """
    Generate a detailed PDF/HTML report of consensus analysis
    Includes cluster descriptions, key statements, and recommendations
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        flash("No analysis available to generate report", "warning")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id,
                              slug=discussion.slug))
    
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
    
    # Get latest analysis
    analysis = ConsensusAnalysis.query.filter_by(
        discussion_id=discussion_id
    ).order_by(ConsensusAnalysis.created_at.desc()).first()
    
    if not analysis:
        return jsonify({'error': 'No analysis available'}), 404
    
    export_format = request.args.get('format', 'json')
    
    if export_format == 'csv':
        # TODO: Implement CSV export
        flash("CSV export coming soon", "info")
        return redirect(url_for('consensus.view_results', discussion_id=discussion_id))
    
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
            statement = Statement.query.get(stmt['statement_id'])
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
            analysis.cluster_data['summary_generated_at'] = datetime.utcnow().isoformat()
            analysis.cluster_data['summary_generated_by'] = current_user.id
            db.session.commit()
            
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
    from flask import jsonify
    
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
            analysis.cluster_data['labels_generated_at'] = datetime.utcnow().isoformat()
            db.session.commit()
            
            flash("Cluster labels generated successfully!", "success")
        else:
            flash("Failed to generate labels. Check your API key status.", "danger")
    
    except Exception as e:
        logger.error(f"Error generating labels: {e}", exc_info=True)
        flash("An error occurred while generating labels", "danger")
    
    return redirect(url_for('consensus.view_results', discussion_id=discussion_id))

