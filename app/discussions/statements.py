# app/discussions/statements.py
"""
Routes for Native Statement System (Phase 1)

Adapted from pol.is patterns with Society Speaks enhancements
"""
from flask import render_template, redirect, url_for, flash, request, Blueprint, jsonify, current_app, session
from flask_login import login_required, current_user
from app import db, limiter
from app.discussions.statement_forms import StatementForm, VoteForm, ResponseForm, FlagStatementForm
from app.models import Discussion, Statement, StatementVote, Response, StatementFlag
from sqlalchemy import func, desc, or_
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timedelta
import hashlib

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


def get_user_identifier():
    """
    Get identifier for current user (authenticated or anonymous)
    
    Returns dict with:
    - user_id: ID if authenticated, None if anonymous
    - session_fingerprint: Hash of session + IP for anonymous tracking
    """
    if current_user.is_authenticated:
        return {
            'user_id': current_user.id,
            'session_fingerprint': None
        }
    else:
        # Create fingerprint from session ID + IP address
        if 'fingerprint' not in session:
            # Generate stable fingerprint for this session
            session_id = session.get('_id', request.remote_addr or 'unknown')
            ip_addr = request.remote_addr or 'unknown'
            user_agent = request.headers.get('User-Agent', '')[:100]
            
            fingerprint_string = f"{session_id}:{ip_addr}:{user_agent}"
            fingerprint = hashlib.sha256(fingerprint_string.encode()).hexdigest()
            session['fingerprint'] = fingerprint
            session.modified = True
        
        return {
            'user_id': None,
            'session_fingerprint': session['fingerprint']
        }


def check_statement_rate_limit(identifier):
    """
    Check if user has exceeded statement rate limit
    
    Rate limits (per hour):
    - Anonymous users: 5 statements
    - Authenticated users: 10 statements
    
    Returns: (allowed: bool, remaining: int, message: str)
    """
    one_hour_ago = datetime.utcnow() - timedelta(hours=1)
    
    # Build query based on user type
    if identifier['user_id']:
        # Authenticated user - 10 per hour
        rate_limit = 10
        recent_count = Statement.query.filter(
            Statement.user_id == identifier['user_id'],
            Statement.created_at > one_hour_ago
        ).count()
    else:
        # Anonymous user - 5 per hour
        rate_limit = 5
        recent_count = Statement.query.filter(
            Statement.session_fingerprint == identifier['session_fingerprint'],
            Statement.created_at > one_hour_ago
        ).count()
    
    remaining = rate_limit - recent_count
    allowed = recent_count < rate_limit
    
    if not allowed:
        user_type = "logged-in users" if identifier['user_id'] else "anonymous users"
        message = f"Rate limit exceeded. {user_type.capitalize()} can post {rate_limit} statements per hour. Please try again later."
    else:
        message = None
    
    return allowed, remaining, message


@statements_bp.route('/discussions/<int:discussion_id>/statements/create', methods=['GET', 'POST'])
@limiter.limit("10 per minute")  # Removed @login_required to allow anonymous statements like pol.is
def create_statement(discussion_id):
    """Create a new statement in a native discussion (authenticated or anonymous)"""
    discussion = Discussion.query.get_or_404(discussion_id)
    
    if not discussion.has_native_statements:
        flash("This discussion does not support native statements", "error")
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    # Get user identifier (authenticated or anonymous)
    identifier = get_user_identifier()
    
    # Check rate limits (5/hour for anonymous, 10/hour for authenticated)
    allowed, remaining, rate_message = check_statement_rate_limit(identifier)
    if not allowed:
        flash(rate_message, "error")
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
        
        # Phase 4.4: Semantic deduplication (optional, only for authenticated users with LLM)
        from app.models import UserAPIKey
        has_llm = False
        if current_user.is_authenticated:
            has_llm = UserAPIKey.query.filter_by(
                user_id=current_user.id,
                is_active=True
            ).first() is not None
        
        if has_llm and current_user.is_authenticated:
            try:
                from app.lib.llm_utils import find_duplicate_statements
                
                # Get recent statements for comparison
                recent_statements = Statement.query.filter_by(
                    discussion_id=discussion_id,
                    is_deleted=False
                ).order_by(Statement.created_at.desc()).limit(50).all()
                
                statement_dicts = [{'id': s.id, 'content': s.content} for s in recent_statements]
                
                # Check for semantic duplicates
                similar = find_duplicate_statements(
                    new_statement=form.content.data.strip(),
                    existing_statements=statement_dicts,
                    threshold=0.9,
                    user_id=current_user.id,
                    db=db
                )
                
                if similar and len(similar) > 0:
                    # Found similar statements, warn user
                    similar_stmt = Statement.query.get(similar[0]['id'])
                    flash(f"A similar statement already exists: '{similar_stmt.content}'. Consider voting on it instead.", "info")
                    return redirect(url_for('statements.view_statement', statement_id=similar_stmt.id))
            
            except Exception as e:
                # Don't block statement creation if deduplication fails
                current_app.logger.warning(f"Semantic deduplication failed: {e}")
        
        # Create new statement (authenticated or anonymous)
        statement = Statement(
            discussion_id=discussion_id,
            user_id=identifier['user_id'],
            session_fingerprint=identifier['session_fingerprint'],
            content=form.content.data.strip(),
            statement_type=form.statement_type.data
        )
        
        db.session.add(statement)
        db.session.commit()
        
        flash("Statement posted successfully!", "success")
        
        # For anonymous users, show upgrade prompt
        if not current_user.is_authenticated:
            flash("💡 Create a free account to add detailed responses, link evidence, and track your contributions!", "info")
        
        return redirect(url_for('discussions.view_discussion', 
                              discussion_id=discussion.id, 
                              slug=discussion.slug))
    
    return render_template('discussions/create_statement.html', 
                         form=form, 
                         discussion=discussion)


def get_statement_vote_fingerprint():
    """Generate a fingerprint for anonymous statement voters"""
    import hashlib
    if 'statement_vote_fingerprint' not in session:
        session_id = session.get('_id', request.remote_addr or 'unknown')
        ip_addr = request.remote_addr or 'unknown'
        user_agent = request.headers.get('User-Agent', '')[:100]
        fingerprint_string = f"statement_vote:{session_id}:{ip_addr}:{user_agent}"
        session['statement_vote_fingerprint'] = hashlib.sha256(fingerprint_string.encode()).hexdigest()
        session.modified = True
    return session['statement_vote_fingerprint']


@statements_bp.route('/statements/<int:statement_id>/vote', methods=['POST'])
@limiter.limit("30 per minute")
def vote_statement(statement_id):
    """
    Vote on a statement (agree/disagree/unsure)

    Supports both authenticated and anonymous voting (like pol.is):
    - Authenticated users: votes stored in DB with user_id
    - Anonymous users: votes stored in DB with session_fingerprint (can be merged to account later)
    """
    user_agent = request.headers.get('User-Agent', '').lower()
    bot_indicators = ['bot', 'crawler', 'spider', 'preview', 'fetch', 'slurp', 'mediapartners']
    if any(indicator in user_agent for indicator in bot_indicators):
        return jsonify({'error': 'Automated requests not allowed'}), 403
    
    statement = Statement.query.get_or_404(statement_id)

    if request.is_json:
        data = request.get_json()
        if data is None or 'vote' not in data:
            return jsonify({'error': 'Vote value is required'}), 400
        try:
            vote_value = int(data.get('vote'))
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid vote value format'}), 400
        confidence = data.get('confidence', 3)
        try:
            confidence = int(confidence) if confidence is not None else 3
            if confidence < 1 or confidence > 5:
                confidence = 3
        except (ValueError, TypeError):
            confidence = 3
    else:
        vote_raw = request.form.get('vote')
        if vote_raw is None or vote_raw == '':
            return jsonify({'error': 'Vote value is required'}), 400
        try:
            vote_value = int(vote_raw)
        except (ValueError, TypeError):
            return jsonify({'error': 'Invalid vote value format'}), 400
        confidence_raw = request.form.get('confidence', 3)
        try:
            confidence = int(confidence_raw) if confidence_raw else 3
            if confidence < 1 or confidence > 5:
                confidence = 3
        except (ValueError, TypeError):
            confidence = 3

    if vote_value not in [-1, 0, 1]:
        return jsonify({'error': 'Invalid vote value. Must be -1, 0, or 1'}), 400

    try:
        if current_user.is_authenticated:
            existing_vote = StatementVote.query.filter_by(
                statement_id=statement_id,
                user_id=current_user.id
            ).first()

            if existing_vote:
                old_vote = existing_vote.vote
                existing_vote.vote = vote_value
                existing_vote.confidence = confidence
                existing_vote.updated_at = datetime.utcnow()

                if old_vote == 1:
                    statement.vote_count_agree -= 1
                elif old_vote == -1:
                    statement.vote_count_disagree -= 1
                elif old_vote == 0:
                    statement.vote_count_unsure -= 1
            else:
                existing_vote = StatementVote(
                    statement_id=statement_id,
                    user_id=current_user.id,
                    discussion_id=statement.discussion_id,
                    vote=vote_value,
                    confidence=confidence
                )
                db.session.add(existing_vote)

            if vote_value == 1:
                statement.vote_count_agree += 1
            elif vote_value == -1:
                statement.vote_count_disagree += 1
            elif vote_value == 0:
                statement.vote_count_unsure += 1

            db.session.commit()

        else:
            fingerprint = get_statement_vote_fingerprint()
            
            existing_vote = StatementVote.query.filter_by(
                statement_id=statement_id,
                session_fingerprint=fingerprint,
                user_id=None
            ).first()

            if existing_vote:
                old_vote = existing_vote.vote
                existing_vote.vote = vote_value
                existing_vote.confidence = confidence
                existing_vote.updated_at = datetime.utcnow()

                if old_vote == 1:
                    statement.vote_count_agree -= 1
                elif old_vote == -1:
                    statement.vote_count_disagree -= 1
                elif old_vote == 0:
                    statement.vote_count_unsure -= 1
            else:
                existing_vote = StatementVote(
                    statement_id=statement_id,
                    session_fingerprint=fingerprint,
                    discussion_id=statement.discussion_id,
                    vote=vote_value,
                    confidence=confidence
                )
                db.session.add(existing_vote)

            if vote_value == 1:
                statement.vote_count_agree += 1
            elif vote_value == -1:
                statement.vote_count_disagree += 1
            elif vote_value == 0:
                statement.vote_count_unsure += 1

            db.session.commit()
            
    except IntegrityError:
        db.session.rollback()
        statement = Statement.query.get(statement_id)
        if current_user.is_authenticated:
            existing_vote = StatementVote.query.filter_by(
                statement_id=statement_id,
                user_id=current_user.id
            ).first()
        else:
            existing_vote = StatementVote.query.filter_by(
                statement_id=statement_id,
                session_fingerprint=get_statement_vote_fingerprint(),
                user_id=None
            ).first()
        
        if existing_vote and existing_vote.vote != vote_value:
            old_vote = existing_vote.vote
            existing_vote.vote = vote_value
            existing_vote.confidence = confidence
            existing_vote.updated_at = datetime.utcnow()
            
            if old_vote == 1:
                statement.vote_count_agree = max(0, statement.vote_count_agree - 1)
            elif old_vote == -1:
                statement.vote_count_disagree = max(0, statement.vote_count_disagree - 1)
            elif old_vote == 0:
                statement.vote_count_unsure = max(0, statement.vote_count_unsure - 1)
            
            if vote_value == 1:
                statement.vote_count_agree += 1
            elif vote_value == -1:
                statement.vote_count_disagree += 1
            elif vote_value == 0:
                statement.vote_count_unsure += 1
            
            db.session.commit()

    return jsonify({
        'success': True,
        'vote': vote_value,
        'vote_count_agree': statement.vote_count_agree,
        'vote_count_disagree': statement.vote_count_disagree,
        'vote_count_unsure': statement.vote_count_unsure,
        'total_votes': statement.total_votes,
        'agreement_rate': statement.agreement_rate,
        'controversy_score': statement.controversy_score
    })


@statements_bp.route('/statements/<int:statement_id>')
def view_statement(statement_id):
    """View a single statement with its responses and votes"""
    statement = Statement.query.get_or_404(statement_id)
    discussion = statement.discussion
    
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
                         discussion=discussion,
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


# =============================================================================
# PHASE 2: RESPONSE ROUTES (Threaded Pro/Con Arguments)
# =============================================================================

@statements_bp.route('/statements/<int:statement_id>/responses/create', methods=['GET', 'POST'])
@login_required
@limiter.limit("20 per minute")
def create_response(statement_id):
    """
    Create a threaded response to a statement or another response
    Supports pro/con/neutral positioning
    """
    statement = Statement.query.get_or_404(statement_id)
    form = ResponseForm()
    
    if form.validate_on_submit():
        try:
            response = Response(
                statement_id=statement.id,
                user_id=current_user.id,
                parent_response_id=None,  # Top-level response
                position=form.position.data,
                content=form.content.data
            )
            db.session.add(response)
            db.session.commit()
            
            flash("Response posted successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=statement.id))
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error creating response: {e}")
            flash("An error occurred while posting your response", "danger")
    
    # GET request - show the response form
    return render_template('discussions/create_response.html', 
                         statement=statement, 
                         form=form)


@statements_bp.route('/responses/<int:response_id>')
def view_response(response_id):
    """View a specific response with its thread"""
    response = Response.query.get_or_404(response_id)
    
    if response.is_deleted:
        flash("This response has been deleted", "info")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Get the full thread (parent responses up to the root)
    thread = []
    current_response = response
    while current_response:
        thread.insert(0, current_response)
        current_response = current_response.parent_response if current_response.parent_response_id else None
    
    # Get child responses
    children = Response.query.filter_by(
        parent_response_id=response.id,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    return render_template('discussions/view_response.html', 
                         response=response,
                         thread=thread,
                         children=children)


@statements_bp.route('/responses/<int:response_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_response(response_id):
    """
    Edit a response (within 10-minute window)
    Only the author can edit
    """
    response = Response.query.get_or_404(response_id)
    
    # Check ownership
    if response.user_id != current_user.id:
        flash("You can only edit your own responses", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Check if deleted
    if response.is_deleted:
        flash("Cannot edit a deleted response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Check 10-minute edit window
    edit_deadline = response.created_at + timedelta(minutes=10)
    if datetime.utcnow() > edit_deadline:
        flash("Edit window has expired (10 minutes)", "warning")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    form = ResponseForm(obj=response)
    
    if form.validate_on_submit():
        try:
            response.content = form.content.data
            response.position = form.position.data
            response.updated_at = datetime.utcnow()
            db.session.commit()
            
            flash("Response updated successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
        except ValueError as e:
            flash(str(e), "danger")
    
    return render_template('discussions/edit_response.html', form=form, response=response)


@statements_bp.route('/responses/<int:response_id>/delete', methods=['POST'])
@login_required
def delete_response(response_id):
    """
    Soft-delete a response
    Only the author or discussion owner can delete
    """
    response = Response.query.get_or_404(response_id)
    discussion = response.statement.discussion
    
    # Check permissions
    if response.user_id != current_user.id and discussion.creator_id != current_user.id:
        flash("You don't have permission to delete this response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    response.is_deleted = True
    db.session.commit()
    
    flash("Response deleted successfully", "success")
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/statements/<int:statement_id>/responses')
def list_responses(statement_id):
    """
    List all responses for a statement (threaded structure)
    Returns JSON for AJAX or HTML for direct access
    """
    statement = Statement.query.get_or_404(statement_id)
    
    # Get top-level responses (no parent)
    responses = Response.query.filter_by(
        statement_id=statement_id,
        parent_response_id=None,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    def build_response_tree(response):
        """Recursively build response tree"""
        children = Response.query.filter_by(
            parent_response_id=response.id,
            is_deleted=False
        ).order_by(Response.created_at.asc()).all()
        
        return {
            'id': response.id,
            'content': response.content,
            'position': response.position,
            'user': response.user.name if response.user else 'Unknown',
            'created_at': response.created_at.isoformat(),
            'children': [build_response_tree(child) for child in children]
        }
    
    # Return JSON for AJAX requests
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'statement_id': statement.id,
            'response_count': len(responses),
            'responses': [build_response_tree(r) for r in responses]
        })
    
    # Return HTML for direct access
    return render_template('discussions/list_responses.html',
                         statement=statement,
                         responses=responses)


@statements_bp.route('/api/responses/<int:response_id>/children')
def get_response_children(response_id):
    """
    Get child responses for lazy loading in threaded view
    Used for expanding/collapsing threads
    """
    response = Response.query.get_or_404(response_id)
    
    children = Response.query.filter_by(
        parent_response_id=response_id,
        is_deleted=False
    ).order_by(Response.created_at.asc()).all()
    
    return jsonify({
        'response_id': response_id,
        'children': [{
            'id': child.id,
            'content': child.content,
            'position': child.position,
            'user': child.user.name if child.user else 'Unknown',
            'created_at': child.created_at.isoformat(),
            'has_children': Response.query.filter_by(parent_response_id=child.id, is_deleted=False).count() > 0
        } for child in children]
    })


# =============================================================================
# PHASE 2: EVIDENCE ROUTES (Citations & File Uploads)
# =============================================================================

@statements_bp.route('/responses/<int:response_id>/evidence/add', methods=['POST'])
@login_required
@limiter.limit("10 per minute")
def add_evidence(response_id):
    """
    Add evidence to a response (citation, URL, or file upload)
    Uses Replit Object Storage for file uploads
    """
    from app.discussions.statement_forms import EvidenceForm
    from app.models import Evidence
    import os
    
    response = Response.query.get_or_404(response_id)
    
    # Check if user can add evidence (response author or discussion owner)
    if response.user_id != current_user.id and response.statement.discussion.creator_id != current_user.id:
        flash("You don't have permission to add evidence to this response", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    form = EvidenceForm()
    
    if form.validate_on_submit():
        try:
            evidence = Evidence(
                response_id=response.id,
                source_title=form.source_title.data,
                source_url=form.source_url.data,
                citation=form.citation.data,
                added_by_user_id=current_user.id
            )
            
            # Handle file upload to Replit Object Storage
            if 'file' in request.files and request.files['file'].filename:
                file = request.files['file']
                
                # Validate file size (max 10MB)
                file.seek(0, os.SEEK_END)
                file_size = file.tell()
                file.seek(0)
                
                if file_size > 10 * 1024 * 1024:  # 10MB
                    flash("File size must be under 10MB", "danger")
                    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
                
                # Upload to Replit Object Storage
                try:
                    from replit.object_storage import Client
                    storage_client = Client()
                    
                    # Generate unique key
                    import uuid
                    file_extension = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else ''
                    storage_key = f"evidence/{response.statement.discussion_id}/{response.id}/{uuid.uuid4()}.{file_extension}"
                    
                    # Upload file
                    file_content = file.read()
                    storage_client.upload_from_bytes(storage_key, file_content)
                    
                    # Get public URL
                    evidence.storage_key = storage_key
                    evidence.storage_url = f"https://replitstorage.com/{storage_key}"  # Adjust based on Replit's actual URL pattern
                    
                except Exception as e:
                    current_app.logger.error(f"Error uploading to Replit storage: {e}")
                    flash("Error uploading file. Please try again.", "danger")
                    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
            
            db.session.add(evidence)
            db.session.commit()
            
            flash("Evidence added successfully!", "success")
            return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
            
        except ValueError as e:
            flash(str(e), "danger")
        except Exception as e:
            current_app.logger.error(f"Error adding evidence: {e}")
            flash("An error occurred while adding evidence", "danger")
    
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/evidence/<int:evidence_id>/delete', methods=['POST'])
@login_required
def delete_evidence(evidence_id):
    """
    Delete evidence (and remove file from Replit Object Storage if applicable)
    Only the user who added it or discussion owner can delete
    """
    from app.models import Evidence
    
    evidence = Evidence.query.get_or_404(evidence_id)
    response = evidence.response
    discussion = response.statement.discussion
    
    # Check permissions
    if evidence.added_by_user_id != current_user.id and discussion.creator_id != current_user.id:
        flash("You don't have permission to delete this evidence", "danger")
        return redirect(url_for('statements.view_statement', statement_id=response.statement_id))
    
    # Delete file from Replit Object Storage if exists
    if evidence.storage_key:
        try:
            from replit.object_storage import Client
            storage_client = Client()
            storage_client.delete(evidence.storage_key)
        except Exception as e:
            current_app.logger.error(f"Error deleting file from storage: {e}")
            # Continue with database deletion even if storage deletion fails
    
    db.session.delete(evidence)
    db.session.commit()
    
    flash("Evidence deleted successfully", "success")
    return redirect(url_for('statements.view_statement', statement_id=response.statement_id))


@statements_bp.route('/evidence/<int:evidence_id>/update-quality', methods=['POST'])
@login_required
def update_evidence_quality(evidence_id):
    """
    Update evidence quality status (pending/verified/disputed)
    Only discussion owner or moderators can update
    """
    from app.models import Evidence
    
    evidence = Evidence.query.get_or_404(evidence_id)
    discussion = evidence.response.statement.discussion
    
    # Check permissions (discussion owner only for now)
    if discussion.creator_id != current_user.id:
        flash("Only the discussion owner can update evidence quality", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    quality_status = request.form.get('quality_status')
    if quality_status not in ['pending', 'verified', 'disputed']:
        flash("Invalid quality status", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    evidence.quality_status = quality_status
    db.session.commit()
    
    flash(f"Evidence marked as {quality_status}", "success")
    return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))


@statements_bp.route('/api/evidence/<int:evidence_id>/download')
def download_evidence(evidence_id):
    """
    Download evidence file from Replit Object Storage
    """
    from app.models import Evidence
    from flask import send_file
    import io
    
    evidence = Evidence.query.get_or_404(evidence_id)
    
    if not evidence.storage_key:
        flash("No file attached to this evidence", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))
    
    try:
        from replit.object_storage import Client
        storage_client = Client()
        
        # Download file from storage
        file_content = storage_client.download_as_bytes(evidence.storage_key)
        
        # Get original filename
        filename = evidence.storage_key.split('/')[-1]
        
        # Return file
        return send_file(
            io.BytesIO(file_content),
            as_attachment=True,
            download_name=filename,
            mimetype='application/octet-stream'
        )
        
    except Exception as e:
        current_app.logger.error(f"Error downloading evidence file: {e}")
        flash("Error downloading file", "danger")
        return redirect(url_for('statements.view_statement', statement_id=evidence.response.statement_id))

