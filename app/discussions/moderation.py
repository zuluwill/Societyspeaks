# app/discussions/moderation.py
"""
Moderation Queue System (Phase 2.3)

Allows discussion owners to review and act on flagged content
"""
from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db, limiter
from app.models import Discussion, Statement, StatementFlag, Response
from sqlalchemy import desc, func
from datetime import datetime
from app.lib.time import utcnow_naive

moderation_bp = Blueprint('moderation', __name__)


@moderation_bp.route('/discussions/<int:discussion_id>/moderation')
@login_required
def moderation_queue(discussion_id):
    """
    View moderation queue for a discussion
    Only accessible to discussion owner
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Check if current user is the discussion owner
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can access the moderation queue", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Get all pending flags
    pending_flags = StatementFlag.query.join(Statement).filter(
        Statement.discussion_id == discussion_id,
        StatementFlag.status == 'pending'
    ).order_by(StatementFlag.created_at.desc()).all()
    
    # Get moderation statistics
    stats = {
        'pending': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'pending'
        ).count(),
        'approved': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'approved'
        ).count(),
        'rejected': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'rejected'
        ).count(),
        'total_statements': Statement.query.filter_by(
            discussion_id=discussion_id,
            is_deleted=False
        ).count(),
        'deleted_statements': Statement.query.filter_by(
            discussion_id=discussion_id,
            is_deleted=True
        ).count()
    }
    
    # Group flags by reason
    flags_by_reason = db.session.query(
        StatementFlag.flag_reason,
        func.count(StatementFlag.id).label('count')
    ).join(Statement).filter(
        Statement.discussion_id == discussion_id,
        StatementFlag.status == 'pending'
    ).group_by(StatementFlag.flag_reason).all()
    
    return render_template('discussions/moderation_queue.html',
                         discussion=discussion,
                         pending_flags=pending_flags,
                         stats=stats,
                         flags_by_reason=dict(flags_by_reason))


@moderation_bp.route('/discussions/<int:discussion_id>/moderation/review/<int:flag_id>', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def review_flag(discussion_id, flag_id):
    """
    Review a flag and take action (approve or reject)
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    flag = StatementFlag.query.get_or_404(flag_id)
    
    # Check permissions
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can review flags", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Check that flag belongs to this discussion
    if flag.statement.discussion_id != discussion_id:
        flash("Invalid flag for this discussion", "danger")
        return redirect(url_for('moderation.moderation_queue', discussion_id=discussion_id))
    
    action = request.form.get('action')
    
    if action == 'approve':
        # Approve the flag - mark statement as problematic
        flag.status = 'approved'
        flag.reviewed_by_user_id = current_user.id
        flag.reviewed_at = utcnow_naive()
        
        # Update statement moderation status
        flag.statement.mod_status = -1  # Rejected
        
        # Optionally delete the statement
        if request.form.get('delete_statement') == 'yes':
            flag.statement.is_deleted = True
        
        db.session.commit()
        flash("Flag approved. Statement has been moderated.", "success")
        
    elif action == 'reject':
        # Reject the flag - content is fine
        flag.status = 'rejected'
        flag.reviewed_by_user_id = current_user.id
        flag.reviewed_at = utcnow_naive()
        
        # Mark statement as accepted
        flag.statement.mod_status = 1  # Accepted
        
        db.session.commit()
        flash("Flag rejected. Statement is acceptable.", "success")
        
    else:
        flash("Invalid action", "danger")
    
    return redirect(url_for('moderation.moderation_queue', discussion_id=discussion_id))


@moderation_bp.route('/discussions/<int:discussion_id>/moderation/bulk-action', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def bulk_moderation_action(discussion_id):
    """
    Take bulk action on multiple flags
    Useful for handling spam waves
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Check permissions
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can perform bulk actions", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    flag_ids = request.form.getlist('flag_ids')
    action = request.form.get('action')
    
    if not flag_ids:
        flash("No flags selected", "warning")
        return redirect(url_for('moderation.moderation_queue', discussion_id=discussion_id))
    
    # Get all selected flags
    flags = StatementFlag.query.filter(
        StatementFlag.id.in_(flag_ids),
        StatementFlag.status == 'pending'
    ).all()
    
    # Verify all flags belong to this discussion
    for flag in flags:
        if flag.statement.discussion_id != discussion_id:
            flash("Invalid flag detected in selection", "danger")
            return redirect(url_for('moderation.moderation_queue', discussion_id=discussion_id))
    
    count = 0
    if action == 'approve_all':
        for flag in flags:
            flag.status = 'approved'
            flag.reviewed_by_user_id = current_user.id
            flag.reviewed_at = utcnow_naive()
            flag.statement.mod_status = -1
            if request.form.get('delete_statements') == 'yes':
                flag.statement.is_deleted = True
            count += 1
        db.session.commit()
        flash(f"{count} flags approved", "success")
        
    elif action == 'reject_all':
        for flag in flags:
            flag.status = 'rejected'
            flag.reviewed_by_user_id = current_user.id
            flag.reviewed_at = utcnow_naive()
            flag.statement.mod_status = 1
            count += 1
        db.session.commit()
        flash(f"{count} flags rejected", "success")
        
    else:
        flash("Invalid bulk action", "danger")
    
    return redirect(url_for('moderation.moderation_queue', discussion_id=discussion_id))


@moderation_bp.route('/discussions/<int:discussion_id>/moderation/stats')
@login_required
def moderation_stats(discussion_id):
    """
    View detailed moderation statistics for a discussion
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Check permissions
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can view moderation stats", "danger")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Calculate comprehensive stats
    stats = {
        'total_statements': Statement.query.filter_by(discussion_id=discussion_id).count(),
        'active_statements': Statement.query.filter_by(discussion_id=discussion_id, is_deleted=False).count(),
        'deleted_statements': Statement.query.filter_by(discussion_id=discussion_id, is_deleted=True).count(),
        'flagged_statements': db.session.query(Statement.id).join(StatementFlag).filter(
            Statement.discussion_id == discussion_id
        ).distinct().count(),
        'pending_flags': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'pending'
        ).count(),
        'approved_flags': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'approved'
        ).count(),
        'rejected_flags': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'rejected'
        ).count(),
    }
    
    # Flag reasons breakdown
    flag_reasons = db.session.query(
        StatementFlag.flag_reason,
        func.count(StatementFlag.id).label('count'),
        func.avg(func.case([(StatementFlag.status == 'approved', 1)], else_=0)).label('approval_rate')
    ).join(Statement).filter(
        Statement.discussion_id == discussion_id
    ).group_by(StatementFlag.flag_reason).all()
    
    # Top flagged users (potential bad actors)
    top_flagged_users = db.session.query(
        Statement.user_id,
        func.count(StatementFlag.id).label('flag_count')
    ).join(StatementFlag).filter(
        Statement.discussion_id == discussion_id
    ).group_by(Statement.user_id).order_by(desc('flag_count')).limit(10).all()
    
    # Top flaggers (users reporting content)
    top_flaggers = db.session.query(
        StatementFlag.flagger_user_id,
        func.count(StatementFlag.id).label('flag_count'),
        func.avg(func.case([(StatementFlag.status == 'approved', 1)], else_=0)).label('accuracy')
    ).join(Statement).filter(
        Statement.discussion_id == discussion_id
    ).group_by(StatementFlag.flagger_user_id).order_by(desc('flag_count')).limit(10).all()
    
    return render_template('discussions/moderation_stats.html',
                         discussion=discussion,
                         stats=stats,
                         flag_reasons=flag_reasons,
                         top_flagged_users=top_flagged_users,
                         top_flaggers=top_flaggers)


@moderation_bp.route('/api/discussions/<int:discussion_id>/moderation/summary')
@login_required
def moderation_summary_api(discussion_id):
    """
    JSON API endpoint for moderation summary
    Used for dashboard widgets
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    # Check permissions
    if discussion.creator_id != current_user.id:
        return jsonify({'error': 'Permission denied'}), 403
    
    stats = {
        'pending_flags': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'pending'
        ).count(),
        'requires_attention': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status == 'pending',
            StatementFlag.flag_reason.in_(['offensive', 'spam'])
        ).count(),
        'total_moderation_actions': StatementFlag.query.join(Statement).filter(
            Statement.discussion_id == discussion_id,
            StatementFlag.status.in_(['approved', 'rejected'])
        ).count()
    }
    
    return jsonify(stats)

