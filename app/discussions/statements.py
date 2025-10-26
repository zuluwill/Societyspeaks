# app/discussions/statements.py
"""
Routes for Native Statement System (Phase 1)

Adapted from pol.is patterns with Society Speaks enhancements
"""
from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app
from flask_login import login_required, current_user
from app import db, limiter
from app.discussions.statement_forms import StatementForm, VoteForm, ResponseForm, FlagStatementForm
from app.models import Discussion, Statement, StatementVote, Response, StatementFlag
from sqlalchemy import func, desc
from datetime import datetime, timedelta

statements_bp = Blueprint('statements', __name__)


def calculate_wilson_score(agree, disagree, confidence=0.95):
    """
    Wilson score confidence interval for statement ranking
    Better than simple ratio for sparse data
    """
    from math import sqrt
    try:
        from scipy import stats
        n = agree + disagree
        if n == 0:
            return 0
        
        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        phat = agree / n
        
        return (phat + z*z/(2*n) - z * sqrt((phat*(1-phat)+z*z/(4*n))/n))/(1+z*z/n)
    except ImportError:
        # Fallback if scipy not available
        n = agree + disagree
        if n == 0:
            return 0
        return agree / n


@statements_bp.route('/discussions/<int:discussion_id>/statements/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("10 per minute")
def create_statement(discussion_id):
    """Create a new statement in a native discussion"""
    discussion = Discussion.query.get_or_404(discussion_id)
    
    if not discussion.has_native_statements:
        flash("This discussion does not support native statements", "error")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    form = StatementForm()
    
    if form.validate_on_submit():
        # Check for duplicate content (pol.is pattern)
        existing = Statement.query.filter_by(
            discussion_id=discussion_id,
            content=form.content.data.strip()
        ).first()
        
        if existing:
            flash("This statement already exists in the discussion", "warning")
            return redirect(url_for('statements.view_statement', statement_id=existing.id))
        
        # Create new statement
        statement = Statement(
            discussion_id=discussion_id,
            user_id=current_user.id,
            content=form.content.data.strip(),
            statement_type=form.statement_type.data
        )
        
        db.session.add(statement)
        db.session.commit()
        
        flash("Statement posted successfully!", "success")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    return render_template('discussions/create_statement.html', 
                         form=form, 
                         discussion=discussion)


@statements_bp.route('/statements/<int:statement_id>/vote', methods=['POST'])
@login_required
@limiter.limit("30 per minute")
def vote_statement(statement_id):
    """Vote on a statement (agree/disagree/unsure)"""
    statement = Statement.query.get_or_404(statement_id)
    
    # Get vote value from request
    vote_value = request.form.get('vote', type=int)
    confidence = request.form.get('confidence', type=int)
    
    if vote_value not in [-1, 0, 1]:
        return jsonify({'error': 'Invalid vote value'}), 400
    
    # Check if user already voted (pol.is allows vote changes)
    existing_vote = StatementVote.query.filter_by(
        statement_id=statement_id,
        user_id=current_user.id
    ).first()
    
    if existing_vote:
        # Update existing vote
        old_vote = existing_vote.vote
        existing_vote.vote = vote_value
        existing_vote.confidence = confidence
        existing_vote.updated_at = datetime.utcnow()
        
        # Update denormalized counts
        if old_vote == 1:
            statement.vote_count_agree -= 1
        elif old_vote == -1:
            statement.vote_count_disagree -= 1
        elif old_vote == 0:
            statement.vote_count_unsure -= 1
            
    else:
        # Create new vote
        existing_vote = StatementVote(
            statement_id=statement_id,
            user_id=current_user.id,
            discussion_id=statement.discussion_id,
            vote=vote_value,
            confidence=confidence
        )
        db.session.add(existing_vote)
    
    # Update denormalized counts
    if vote_value == 1:
        statement.vote_count_agree += 1
    elif vote_value == -1:
        statement.vote_count_disagree += 1
    elif vote_value == 0:
        statement.vote_count_unsure += 1
    
    db.session.commit()
    
    # Return updated vote counts
    return jsonify({
        'success': True,
        'vote': vote_value,
        'counts': {
            'agree': statement.vote_count_agree,
            'disagree': statement.vote_count_disagree,
            'unsure': statement.vote_count_unsure,
            'total': statement.total_votes
        }
    })


@statements_bp.route('/statements/<int:statement_id>')
def view_statement(statement_id):
    """View a single statement with its responses and votes"""
    statement = Statement.query.get_or_404(statement_id)
    
    # Get user's vote if logged in
    user_vote = None
    if current_user.is_authenticated:
        user_vote = StatementVote.query.filter_by(
            statement_id=statement_id,
            user_id=current_user.id
        ).first()
    
    # Get responses
    responses = Response.query.filter_by(
        statement_id=statement_id,
        is_deleted=False
    ).order_by(Response.created_at.desc()).all()
    
    return render_template('discussions/view_statement.html',
                         statement=statement,
                         user_vote=user_vote,
                         responses=responses)


@statements_bp.route('/statements/<int:statement_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_statement(statement_id):
    """Edit own statement (within 10 minute window)"""
    statement = Statement.query.get_or_404(statement_id)
    
    # Check ownership
    if statement.user_id != current_user.id:
        flash("You can only edit your own statements", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    # Check edit window (10 minutes like pol.is)
    if datetime.utcnow() - statement.created_at > timedelta(minutes=10):
        flash("Edit window expired (10 minutes)", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    form = StatementForm(obj=statement)
    
    if form.validate_on_submit():
        statement.content = form.content.data.strip()
        statement.statement_type = form.statement_type.data
        statement.updated_at = datetime.utcnow()
        db.session.commit()
        
        flash("Statement updated successfully", "success")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    return render_template('discussions/edit_statement.html', 
                         form=form, 
                         statement=statement)


@statements_bp.route('/statements/<int:statement_id>/delete', methods=['POST'])
@login_required
def delete_statement(statement_id):
    """Soft delete own statement"""
    statement = Statement.query.get_or_404(statement_id)
    
    # Check ownership or admin
    if statement.user_id != current_user.id and not current_user.is_admin:
        flash("You can only delete your own statements", "error")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    statement.is_deleted = True
    db.session.commit()
    
    flash("Statement deleted", "success")
    return redirect(url_for('discussions.view_discussion', 
                          discussion_id=statement.discussion_id, 
                          slug=statement.discussion.slug))


@statements_bp.route('/statements/<int:statement_id>/flag', methods=['GET', 'POST'])
@login_required
@limiter.limit("5 per minute")
def flag_statement(statement_id):
    """Flag a statement for moderation"""
    statement = Statement.query.get_or_404(statement_id)
    
    # Check if user already flagged this statement
    existing_flag = StatementFlag.query.filter_by(
        statement_id=statement_id,
        flagger_user_id=current_user.id
    ).first()
    
    if existing_flag:
        flash("You've already flagged this statement", "warning")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    form = FlagStatementForm()
    
    if form.validate_on_submit():
        flag = StatementFlag(
            statement_id=statement_id,
            flagger_user_id=current_user.id,
            flag_reason=form.flag_reason.data,
            additional_context=form.additional_context.data
        )
        db.session.add(flag)
        db.session.commit()
        
        flash("Statement flagged for review", "success")
        return redirect(url_for('statements.view_statement', statement_id=statement_id))
    
    return render_template('discussions/flag_statement.html', 
                         form=form, 
                         statement=statement)


@statements_bp.route('/discussions/<int:discussion_id>/statements')
def list_statements(discussion_id):
    """
    List statements for a discussion with sorting options
    Progressive disclosure: prioritize statements with fewer votes
    """
    discussion = Discussion.query.get_or_404(discussion_id)
    
    if not discussion.has_native_statements:
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Get sort parameter
    sort = request.args.get('sort', 'best')
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Base query
    query = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    )
    
    # Apply moderation filter
    if not (current_user.is_authenticated and 
            (current_user.id == discussion.creator_id or current_user.is_admin)):
        # Non-owners only see approved statements
        query = query.filter(Statement.mod_status >= 0)
    
    # Apply sorting
    if sort == 'best':
        # Wilson score ranking (needs to be calculated in Python)
        # For now, use simple agreement rate
        query = query.order_by(desc(Statement.vote_count_agree))
    elif sort == 'controversial':
        # Order by controversy score (calculated in model)
        statements = query.all()
        statements.sort(key=lambda s: s.controversy_score, reverse=True)
        # Convert to paginated format
        start = (page - 1) * per_page
        end = start + per_page
        paginated_statements = statements[start:end]
        total = len(statements)
        return render_template('discussions/list_statements.html',
                             discussion=discussion,
                             statements=paginated_statements,
                             sort=sort,
                             page=page,
                             total=total,
                             per_page=per_page)
    elif sort == 'recent':
        query = query.order_by(desc(Statement.created_at))
    elif sort == 'most_voted':
        # Order by total votes
        query = query.order_by(
            desc(Statement.vote_count_agree + 
                 Statement.vote_count_disagree + 
                 Statement.vote_count_unsure))
    elif sort == 'progressive':
        # Progressive disclosure: prioritize statements with fewer votes
        # This is the pol.is pattern
        query = query.order_by(
            (Statement.vote_count_agree + 
             Statement.vote_count_disagree + 
             Statement.vote_count_unsure).asc(),
            func.random()  # Shuffle within same vote count
        )
    else:
        query = query.order_by(desc(Statement.created_at))
    
    # Paginate
    statements = query.paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('discussions/list_statements.html',
                         discussion=discussion,
                         statements=statements,
                         sort=sort)


# API endpoints for AJAX voting

@statements_bp.route('/api/statements/<int:statement_id>/votes')
def get_statement_votes(statement_id):
    """Get vote breakdown for a statement (API endpoint)"""
    statement = Statement.query.get_or_404(statement_id)
    
    return jsonify({
        'statement_id': statement.id,
        'counts': {
            'agree': statement.vote_count_agree,
            'disagree': statement.vote_count_disagree,
            'unsure': statement.vote_count_unsure,
            'total': statement.total_votes
        },
        'stats': {
            'agreement_rate': statement.agreement_rate,
            'controversy_score': statement.controversy_score
        }
    })

