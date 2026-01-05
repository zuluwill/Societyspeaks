# app/admin/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, IndividualProfile, CompanyProfile, Discussion, DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber, Statement, TrendingTopic
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from app.admin.forms import UserAssignmentForm
from functools import wraps
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from app.utils import upload_to_object_storage  
from app.email_utils import send_email
from app.admin import admin_bp
import time




def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_admin:
            flash('You need administrator privileges to access this area.', 'error')
            return redirect(url_for('main.index'))
        return f(*args, **kwargs)
    return decorated_function


# Admin dashboard
@admin_bp.route('/dashboard')
@login_required
@admin_required
def dashboard():
    users_count = User.query.count()
    individual_profiles_count = IndividualProfile.query.count()
    company_profiles_count = CompanyProfile.query.count()
    discussions_count = Discussion.query.count()

    return render_template(
        'admin/admin_dashboard.html',
        users_count=users_count,
        individual_profiles_count=individual_profiles_count,
        company_profiles_count=company_profiles_count,
        discussions_count=discussions_count
    )


# Profile Management Routes
@admin_bp.route('/profiles')
@login_required
@admin_required
def list_profiles():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    individual_profiles = IndividualProfile.query.options(
        db.joinedload(IndividualProfile.user)
    ).order_by(IndividualProfile.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    company_profiles = CompanyProfile.query.options(
        db.joinedload(CompanyProfile.user)
    ).order_by(CompanyProfile.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template(
        'admin/profiles/list.html',
        individual_profiles=individual_profiles,
        company_profiles=company_profiles
    )


@admin_bp.route('/profiles/individual/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_individual_profile():
    form = IndividualProfileForm()
    user_form = UserAssignmentForm()

    if form.validate_on_submit() and user_form.validate():
        try:
            profile_image = handle_image_upload(form.profile_image.data, 'profile')
            banner_image = handle_image_upload(form.banner_image.data, 'banner')
            user = create_or_get_user(user_form)

            profile = IndividualProfile(
                user_id=user.id,
                full_name=form.full_name.data,
                bio=form.bio.data,
                profile_image=profile_image,
                banner_image=banner_image,
                city=form.city.data,
                country=form.country.data,
                email=form.email.data,
                website=form.website.data,
                linkedin_url=form.linkedin_url.data,
                twitter_url=form.twitter_url.data,
                facebook_url=form.facebook_url.data,
                instagram_url=form.instagram_url.data,
                tiktok_url=form.tiktok_url.data
            )

            user.profile_type = 'individual'
            db.session.add(profile)

            if user_form.assignment_type.data == 'new':
                send_welcome_email(user.email, user_form.username.data, user_form.password.data)

            db.session.commit()
            flash('Individual profile created successfully!', 'success')
            return redirect(url_for('admin.list_profiles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating profile: {str(e)}")
            flash('Error creating profile. Please try again.', 'error')

    return render_template('admin/profiles/create_individual.html', form=form, user_form=user_form)


@admin_bp.route('/profiles/individual/<int:profile_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_individual_profile(profile_id):
    profile = IndividualProfile.query.get_or_404(profile_id)
    form = IndividualProfileForm(obj=profile)
    user_form = UserAssignmentForm(obj=profile.user)

    if request.method == 'GET':
        user_form.assignment_type.data = 'existing'
        user_form.existing_user.data = str(profile.user_id)

    if form.validate_on_submit() and user_form.validate():
        try:
            if form.profile_image.data:
                profile.profile_image = handle_image_upload(form.profile_image.data, 'profile')
            if form.banner_image.data:
                profile.banner_image = handle_image_upload(form.banner_image.data, 'banner')

            update_profile_fields(profile, form)
            handle_user_reassignment(profile, user_form, 'individual')

            profile.update_slug()
            db.session.commit()
            flash('Profile updated successfully!', 'success')
            return redirect(url_for('admin.list_profiles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile: {str(e)}")
            flash('Error updating profile. Please try again.', 'error')

    return render_template('admin/profiles/edit_individual.html', form=form, user_form=user_form, profile=profile)


@admin_bp.route('/profiles/company/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_company_profile():
    form = CompanyProfileForm()
    user_form = UserAssignmentForm()

    if form.validate_on_submit() and user_form.validate():
        try:
            logo = handle_image_upload(form.logo.data, 'logo')
            banner_image = handle_image_upload(form.banner_image.data, 'banner')
            user = create_or_get_user(user_form)

            profile = CompanyProfile(
                user_id=user.id,
                company_name=form.company_name.data,
                description=form.description.data,
                logo=logo,
                banner_image=banner_image,
                city=form.city.data,
                country=form.country.data,
                email=form.email.data,
                website=form.website.data,
                linkedin_url=form.linkedin_url.data,
                twitter_url=form.twitter_url.data,
                facebook_url=form.facebook_url.data,
                instagram_url=form.instagram_url.data,
                tiktok_url=form.tiktok_url.data
            )

            user.profile_type = 'company'
            db.session.add(profile)

            if user_form.assignment_type.data == 'new':
                send_welcome_email(user.email, user_form.username.data, user_form.password.data)

            db.session.commit()
            flash('Company profile created successfully!', 'success')
            return redirect(url_for('admin.list_profiles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating company profile: {str(e)}")
            flash('Error creating profile. Please try again.', 'error')

    return render_template('admin/profiles/create_company.html', form=form, user_form=user_form)


@admin_bp.route('/profiles/company/<int:profile_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_company_profile(profile_id):
    profile = CompanyProfile.query.get_or_404(profile_id)
    form = CompanyProfileForm(obj=profile)
    user_form = UserAssignmentForm(obj=profile.user)

    if request.method == 'GET':
        user_form.assignment_type.data = 'existing'
        user_form.existing_user.data = str(profile.user_id)

    if form.validate_on_submit() and user_form.validate():
        try:
            if form.logo.data:
                profile.logo = handle_image_upload(form.logo.data, 'logo')
            if form.banner_image.data:
                profile.banner_image = handle_image_upload(form.banner_image.data, 'banner')

            update_profile_fields(profile, form)
            handle_user_reassignment(profile, user_form, 'company')

            profile.update_slug()
            db.session.commit()
            flash('Company profile updated successfully!', 'success')
            return redirect(url_for('admin.list_profiles'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating company profile: {str(e)}")
            flash('Error updating profile. Please try again.', 'error')

    return render_template('admin/profiles/edit_company.html', form=form, user_form=user_form, profile=profile)


@admin_bp.route('/profiles/<string:profile_type>/<int:profile_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_profile(profile_type, profile_id):
    try:
        if profile_type == 'individual':
            profile = IndividualProfile.query.get_or_404(profile_id)
        else:
            profile = CompanyProfile.query.get_or_404(profile_id)

        user = User.query.get(profile.user_id)
        if not user.company_profile and not user.individual_profile:
            user.profile_type = None

        db.session.delete(profile)
        db.session.commit()
        flash('Profile deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting profile: {str(e)}")
        flash('Error deleting profile. Please try again.', 'error')

    return redirect(url_for('admin.list_profiles'))


# Helper Functions
def handle_image_upload(file_data, prefix):
    if file_data:
        filename = secure_filename(file_data.filename)
        filename = f"{prefix}_{int(time.time())}_{filename}"
        upload_to_object_storage(file_data, filename)
        return filename
    return None


def create_or_get_user(user_form):
    if user_form.assignment_type.data == 'existing':
        return User.query.get(user_form.existing_user.data)

    user = User(
        username=user_form.username.data,
        email=user_form.email.data,
        password=generate_password_hash(user_form.password.data)
    )
    db.session.add(user)
    db.session.flush()
    return user


def update_profile_fields(profile, form):
    for field in form.data:
        if field not in ['csrf_token', 'profile_image', 'banner_image', 'logo']:
            setattr(profile, field, form.data[field])


def handle_user_reassignment(profile, user_form, profile_type):
    new_user = create_or_get_user(user_form)
    if profile.user_id != new_user.id:
        old_user = User.query.get(profile.user_id)
        if not (old_user.individual_profile or old_user.company_profile):
            old_user.profile_type = None

        profile.user_id = new_user.id
        new_user.profile_type = profile_type

    if user_form.assignment_type.data == 'new':
        send_welcome_email(new_user.email, user_form.username.data, user_form.password.data)


def send_welcome_email(email, username, password):
    subject = "Welcome to SocietySpeaks - Your Account Details"
    body = f"""
    Hello {username},

    An administrator has created a profile for you on SocietySpeaks. 
    You can login with the following credentials:

    Username: {username}
    Password: {password}

    Please login and change your password immediately.

    Best regards,
    The SocietySpeaks Team
    """
    send_email(email, subject, body)


@admin_bp.route('/discussions/<int:discussion_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_discussion(discussion_id):
    discussion = Discussion.query.get_or_404(discussion_id)
    try:
        db.session.delete(discussion)
        db.session.commit()
        flash('Discussion deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting discussion: {str(e)}")
        flash('Error deleting discussion. Please try again.', 'error')
    
    return redirect(url_for('admin.list_discussions'))


@admin_bp.route('/discussions')
@login_required
@admin_required
def list_discussions():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    discussions = Discussion.query.options(
        db.joinedload(Discussion.creator)
    ).order_by(Discussion.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('admin/discussions/list.html', discussions=discussions)

@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    users = User.query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    return render_template('admin/users/list.html', users=users)

@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.list_users'))
    try:
        # Delete associated data
        if user.individual_profile:
            db.session.delete(user.individual_profile)
        if user.company_profile:
            db.session.delete(user.company_profile)
        # Delete user's discussions
        for discussion in user.discussions_created:
            db.session.delete(discussion)
        db.session.delete(user)
        db.session.commit()
        flash('User and associated data deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting user: {str(e)}")
        flash('Error deleting user. Please try again.', 'error')
    return redirect(url_for('admin.list_users'))

@admin_bp.route('/users/<int:user_id>/toggle-admin', methods=['POST'])
@login_required
@admin_required
def toggle_admin(user_id):
    user = User.query.get_or_404(user_id)
    if user == current_user:
        flash('You cannot modify your own admin status.', 'error')
        return redirect(url_for('admin.list_users'))
    try:
        user.is_admin = not user.is_admin
        db.session.commit()
        flash(f"Admin privileges {'granted to' if user.is_admin else 'removed from'} {user.username}!", 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error toggling admin status: {str(e)}")
        flash('Error updating admin status. Please try again.', 'error')
    return redirect(url_for('admin.list_users'))

@admin_bp.before_request
def log_admin_access():
    if current_user.is_authenticated and current_user.is_admin:
        current_app.logger.info(f"Admin access: {current_user.username} - {request.endpoint}")


@admin_bp.route('/daily-questions')
@login_required
@admin_required
def list_daily_questions():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    questions = DailyQuestion.query.order_by(
        DailyQuestion.question_date.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    today = date.today()
    todays_question = DailyQuestion.get_today()
    
    upcoming = DailyQuestion.query.filter(
        DailyQuestion.question_date > today,
        DailyQuestion.status == 'scheduled'
    ).order_by(DailyQuestion.question_date.asc()).limit(7).all()
    
    return render_template(
        'admin/daily/list.html',
        questions=questions,
        todays_question=todays_question,
        upcoming=upcoming,
        today=today
    )


@admin_bp.route('/daily-questions/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_daily_question():
    if request.method == 'POST':
        try:
            question_date_str = request.form.get('question_date')
            question_date = datetime.strptime(question_date_str, '%Y-%m-%d').date()
            
            existing = DailyQuestion.query.filter_by(question_date=question_date).first()
            if existing:
                flash(f'A question already exists for {question_date}', 'error')
                return redirect(url_for('admin.create_daily_question'))
            
            source_type = request.form.get('source_type', 'manual')
            source_discussion_id = request.form.get('source_discussion_id') or None
            source_statement_id = request.form.get('source_statement_id') or None
            source_trending_topic_id = request.form.get('source_trending_topic_id') or None
            
            question = DailyQuestion(
                question_date=question_date,
                question_number=DailyQuestion.get_next_question_number(),
                question_text=request.form.get('question_text'),
                context=request.form.get('context') or None,
                why_this_question=request.form.get('why_this_question') or None,
                topic_category=request.form.get('topic_category') or None,
                source_type=source_type,
                source_discussion_id=int(source_discussion_id) if source_discussion_id else None,
                source_statement_id=int(source_statement_id) if source_statement_id else None,
                source_trending_topic_id=int(source_trending_topic_id) if source_trending_topic_id else None,
                cold_start_threshold=int(request.form.get('cold_start_threshold', 50)),
                status=request.form.get('status', 'scheduled'),
                created_by_id=current_user.id
            )
            
            if question.status == 'published':
                question.published_at = datetime.utcnow()
            
            db.session.add(question)
            db.session.commit()
            
            flash(f'Daily question #{question.question_number} created successfully!', 'success')
            return redirect(url_for('admin.list_daily_questions'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating daily question: {e}")
            flash('Error creating daily question. Please try again.', 'error')
    
    discussions = Discussion.query.order_by(Discussion.created_at.desc()).limit(50).all()
    trending_topics = TrendingTopic.query.filter_by(status='published').order_by(TrendingTopic.created_at.desc()).limit(20).all()
    topics = Discussion.TOPICS
    
    next_date = date.today()
    while DailyQuestion.query.filter_by(question_date=next_date).first():
        next_date += timedelta(days=1)
    
    return render_template(
        'admin/daily/create.html',
        discussions=discussions,
        trending_topics=trending_topics,
        topics=topics,
        next_date=next_date
    )


@admin_bp.route('/daily-questions/<int:question_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_daily_question(question_id):
    question = DailyQuestion.query.get_or_404(question_id)
    
    if request.method == 'POST':
        try:
            question.question_text = request.form.get('question_text')
            question.context = request.form.get('context') or None
            question.why_this_question = request.form.get('why_this_question') or None
            question.topic_category = request.form.get('topic_category') or None
            question.cold_start_threshold = int(request.form.get('cold_start_threshold', 50))
            
            new_status = request.form.get('status')
            if new_status != question.status:
                question.status = new_status
                if new_status == 'published' and not question.published_at:
                    question.published_at = datetime.utcnow()
            
            db.session.commit()
            flash('Daily question updated successfully!', 'success')
            return redirect(url_for('admin.list_daily_questions'))
            
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating daily question: {e}")
            flash('Error updating daily question. Please try again.', 'error')
    
    topics = Discussion.TOPICS
    return render_template('admin/daily/edit.html', question=question, topics=topics)


@admin_bp.route('/daily-questions/<int:question_id>/publish', methods=['POST'])
@login_required
@admin_required
def publish_daily_question(question_id):
    question = DailyQuestion.query.get_or_404(question_id)
    
    try:
        question.status = 'published'
        question.published_at = datetime.utcnow()
        db.session.commit()
        flash(f'Daily question #{question.question_number} published!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error publishing daily question: {e}")
        flash('Error publishing daily question.', 'error')
    
    return redirect(url_for('admin.list_daily_questions'))


@admin_bp.route('/daily-questions/<int:question_id>/archive', methods=['POST'])
@login_required
@admin_required
def archive_daily_question(question_id):
    question = DailyQuestion.query.get_or_404(question_id)
    
    try:
        question.status = 'archived'
        db.session.commit()
        flash(f'Daily question #{question.question_number} archived.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error archiving daily question: {e}")
        flash('Error archiving daily question.', 'error')
    
    return redirect(url_for('admin.list_daily_questions'))


@admin_bp.route('/daily-questions/<int:question_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_daily_question(question_id):
    question = DailyQuestion.query.get_or_404(question_id)
    
    try:
        DailyQuestionResponse.query.filter_by(daily_question_id=question_id).delete()
        db.session.delete(question)
        db.session.commit()
        flash('Daily question deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting daily question: {e}")
        flash('Error deleting daily question.', 'error')
    
    return redirect(url_for('admin.list_daily_questions'))


@admin_bp.route('/daily-questions/<int:question_id>/view')
@login_required
@admin_required
def view_daily_question(question_id):
    question = DailyQuestion.query.get_or_404(question_id)
    responses = DailyQuestionResponse.query.filter_by(
        daily_question_id=question_id
    ).order_by(DailyQuestionResponse.created_at.desc()).limit(100).all()
    
    return render_template(
        'admin/daily/view.html',
        question=question,
        responses=responses,
        stats=question.vote_percentages
    )


@admin_bp.route('/daily-questions/subscribers')
@login_required
@admin_required
def list_daily_subscribers():
    """View all daily question subscribers"""
    from sqlalchemy.orm import joinedload
    subscribers = DailyQuestionSubscriber.query.options(
        joinedload(DailyQuestionSubscriber.user)
    ).order_by(
        DailyQuestionSubscriber.created_at.desc()
    ).all()
    
    subscribed_user_ids = {s.user_id for s in subscribers if s.user_id}
    available_users = User.query.filter(
        User.email.isnot(None),
        ~User.id.in_(subscribed_user_ids) if subscribed_user_ids else True
    ).order_by(User.username).all()
    
    exclude_patterns = ['test', 'bot', 'fake', 'demo', 'example']
    available_users = [
        u for u in available_users 
        if not any(p in (u.email or '').lower() or p in (u.username or '').lower() 
                   for p in exclude_patterns)
    ]
    
    return render_template(
        'admin/daily/subscribers.html',
        subscribers=subscribers,
        available_users=available_users,
        active_count=sum(1 for s in subscribers if s.is_active),
        total_count=len(subscribers)
    )


@admin_bp.route('/daily-questions/subscribers/bulk-add', methods=['POST'])
@login_required
@admin_required
def bulk_subscribe_users():
    """Subscribe all existing registered users to daily questions"""
    from app.email_utils import bulk_subscribe_existing_users
    
    try:
        subscribed, skipped, already = bulk_subscribe_existing_users()
        flash(f'Subscribed {subscribed} users. {already} already subscribed. {skipped} skipped (test/bot accounts).', 'success')
    except Exception as e:
        current_app.logger.error(f"Bulk subscribe error: {e}")
        flash(f'Error during bulk subscription: {str(e)}', 'error')
    
    return redirect(url_for('admin.list_daily_subscribers'))


@admin_bp.route('/daily-questions/subscribers/add', methods=['POST'])
@login_required
@admin_required
def add_subscriber():
    """Add individual users as subscribers"""
    user_ids = request.form.getlist('user_ids')
    
    if not user_ids:
        flash('No users selected.', 'warning')
        return redirect(url_for('admin.list_daily_subscribers'))
    
    added = 0
    for user_id in user_ids:
        try:
            user = User.query.get(int(user_id))
            if not user or not user.email:
                continue
            
            existing = DailyQuestionSubscriber.query.filter_by(user_id=user.id).first()
            if existing:
                if not existing.is_active:
                    existing.is_active = True
                    db.session.commit()
                    added += 1
                continue
            
            subscriber = DailyQuestionSubscriber(
                email=user.email,
                user_id=user.id,
                is_active=True
            )
            subscriber.generate_magic_token()
            db.session.add(subscriber)
            db.session.commit()
            added += 1
        except Exception as e:
            current_app.logger.error(f"Error adding subscriber {user_id}: {e}")
            db.session.rollback()
    
    flash(f'Added {added} subscriber(s).', 'success')
    return redirect(url_for('admin.list_daily_subscribers'))


@admin_bp.route('/daily-questions/subscribers/<int:subscriber_id>/toggle', methods=['POST'])
@login_required
@admin_required
def toggle_subscriber(subscriber_id):
    """Toggle subscriber active status"""
    subscriber = DailyQuestionSubscriber.query.get_or_404(subscriber_id)
    subscriber.is_active = not subscriber.is_active
    db.session.commit()
    
    status = 'activated' if subscriber.is_active else 'deactivated'
    flash(f'Subscriber {subscriber.email} {status}.', 'success')
    return redirect(url_for('admin.list_daily_subscribers'))


@admin_bp.route('/daily-questions/subscribers/<int:subscriber_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_subscriber(subscriber_id):
    """Delete a subscriber completely"""
    subscriber = DailyQuestionSubscriber.query.get_or_404(subscriber_id)
    email = subscriber.email
    
    db.session.delete(subscriber)
    db.session.commit()
    
    flash(f'Subscriber {email} removed.', 'success')
    return redirect(url_for('admin.list_daily_subscribers'))


@admin_bp.route('/daily-questions/subscribers/bulk-remove', methods=['POST'])
@login_required
@admin_required
def bulk_remove_subscribers():
    """Bulk remove selected subscribers"""
    subscriber_ids = request.form.getlist('subscriber_ids')
    
    if not subscriber_ids:
        flash('No subscribers selected.', 'warning')
        return redirect(url_for('admin.list_daily_subscribers'))
    
    removed = 0
    for sub_id in subscriber_ids:
        try:
            subscriber = DailyQuestionSubscriber.query.get(int(sub_id))
            if subscriber:
                db.session.delete(subscriber)
                removed += 1
        except Exception as e:
            current_app.logger.error(f"Error removing subscriber {sub_id}: {e}")
            db.session.rollback()
    
    db.session.commit()
    flash(f'Removed {removed} subscriber(s).', 'success')
    return redirect(url_for('admin.list_daily_subscribers'))


@admin_bp.route('/daily-questions/subscribers/bulk-import', methods=['POST'])
@login_required
@admin_required
def bulk_import_subscribers():
    """Bulk import email-only subscribers from a list of emails"""
    import re
    
    emails_text = request.form.get('emails', '').strip()
    
    if not emails_text:
        flash('No emails provided.', 'warning')
        return redirect(url_for('admin.list_daily_subscribers'))
    
    # Parse emails - handle comma, newline, semicolon, or space separated
    raw_emails = re.split(r'[,;\s\n]+', emails_text)
    
    # Basic email validation regex
    email_pattern = re.compile(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$')
    
    added = 0
    skipped_duplicate = 0
    skipped_invalid = 0
    
    for email in raw_emails:
        email = email.strip().lower()
        
        if not email:
            continue
            
        if not email_pattern.match(email):
            skipped_invalid += 1
            continue
        
        # Check if already exists (by email)
        existing = DailyQuestionSubscriber.query.filter_by(email=email).first()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                db.session.commit()
                added += 1
            else:
                skipped_duplicate += 1
            continue
        
        # Check if there's a user with this email
        user = User.query.filter_by(email=email).first()
        
        try:
            subscriber = DailyQuestionSubscriber(
                email=email,
                user_id=user.id if user else None,
                is_active=True
            )
            subscriber.generate_magic_token()
            db.session.add(subscriber)
            db.session.commit()
            added += 1
        except Exception as e:
            current_app.logger.error(f"Error adding subscriber {email}: {e}")
            db.session.rollback()
    
    # Build summary message
    msg_parts = []
    if added:
        msg_parts.append(f'{added} added')
    if skipped_duplicate:
        msg_parts.append(f'{skipped_duplicate} already subscribed')
    if skipped_invalid:
        msg_parts.append(f'{skipped_invalid} invalid')
    
    flash(', '.join(msg_parts) if msg_parts else 'No emails processed.', 'success' if added else 'info')
    return redirect(url_for('admin.list_daily_subscribers'))
