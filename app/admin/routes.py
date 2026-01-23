# app/admin/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, IndividualProfile, CompanyProfile, Discussion, DailyQuestion, DailyQuestionResponse, DailyQuestionSubscriber, Statement, TrendingTopic, StatementFlag, DailyQuestionResponseFlag, NewsSource, Subscription, PricingPlan
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from app.admin.forms import UserAssignmentForm
from functools import wraps
from datetime import date, datetime, timedelta
from werkzeug.utils import secure_filename
from werkzeug.security import generate_password_hash
from app.utils import upload_to_object_storage  
# Note: send_email removed during Resend migration. Using inline Resend call for admin welcome emails.
from app.admin import admin_bp
from sqlalchemy.orm import joinedload
from sqlalchemy.exc import IntegrityError
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
    """Send welcome email to admin-created users via Resend"""
    import os
    import requests
    
    api_key = os.environ.get('RESEND_API_KEY')
    if not api_key:
        current_app.logger.error("RESEND_API_KEY not set - cannot send admin welcome email")
        return
    
    base_url = os.environ.get('BASE_URL', 'https://societyspeaks.io')
    from_email = os.environ.get('RESEND_FROM_EMAIL', 'Society Speaks <hello@societyspeaks.io>')
    
    html_content = f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="text-align: center; border-bottom: 2px solid #1e40af; padding-bottom: 20px; margin-bottom: 20px;">
            <h1 style="margin: 0; font-size: 24px; color: #1e40af;">Welcome to Society Speaks</h1>
        </div>
        
        <p>Hello {username},</p>
        
        <p>An administrator has created an account for you on Society Speaks.</p>
        
        <div style="background-color: #f8fafc; border-radius: 8px; padding: 20px; margin: 20px 0;">
            <p style="margin: 0 0 10px 0;"><strong>Username:</strong> {username}</p>
            <p style="margin: 0 0 10px 0;"><strong>Email:</strong> {email}</p>
            <p style="margin: 0;"><strong>Temporary Password:</strong> {password}</p>
        </div>
        
        <p style="color: #dc2626;"><strong>Important:</strong> Please login and change your password immediately.</p>
        
        <div style="text-align: center; margin: 30px 0;">
            <a href="{base_url}/auth/login" style="background-color: #1e40af; color: white; padding: 14px 28px; text-decoration: none; border-radius: 6px; font-weight: 600;">Login Now</a>
        </div>
        
        <p style="color: #6b7280; font-size: 14px; margin-top: 30px;">
            Best regards,<br>
            The Society Speaks Team
        </p>
    </body>
    </html>
    """
    
    try:
        response = requests.post(
            'https://api.resend.com/emails',
            json={
                'from': from_email,
                'to': [email],
                'subject': 'Welcome to Society Speaks - Your Account Details',
                'html': html_content
            },
            headers={
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            },
            timeout=30
        )
        
        if response.status_code == 200:
            current_app.logger.info(f"Admin welcome email sent to {email}")
        else:
            current_app.logger.error(f"Failed to send admin welcome email: {response.status_code} - {response.text}")
    except Exception as e:
        current_app.logger.error(f"Error sending admin welcome email: {e}")


@admin_bp.route('/discussions/<int:discussion_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_discussion(discussion_id):
    """Delete a discussion and all its related data (handles foreign keys properly)"""
    from app.models import (
        DiscussionView, Notification, DiscussionParticipant, Statement,
        StatementVote, Response, StatementFlag,
        ConsensusAnalysis, DiscussionSourceArticle, TrendingTopic,
        BriefItem, DailyQuestion, DailyQuestionSelection
    )
    
    discussion = Discussion.query.get_or_404(discussion_id)
    discussion_title = discussion.title
    
    try:
        # Delete in order of dependencies (children first, then parent)
        
        # 1. Clear nullable FK references (set to NULL instead of delete)
        TrendingTopic.query.filter_by(merged_into_discussion_id=discussion_id).update(
            {'merged_into_discussion_id': None}, synchronize_session=False
        )
        TrendingTopic.query.filter_by(discussion_id=discussion_id).update(
            {'discussion_id': None}, synchronize_session=False
        )
        BriefItem.query.filter_by(discussion_id=discussion_id).update(
            {'discussion_id': None}, synchronize_session=False
        )
        DailyQuestion.query.filter_by(source_discussion_id=discussion_id).update(
            {'source_discussion_id': None}, synchronize_session=False
        )
        DailyQuestionSelection.query.filter_by(source_discussion_id=discussion_id).update(
            {'source_discussion_id': None}, synchronize_session=False
        )
        
        # 2. Delete statement-related data (deepest children first)
        statement_ids = [s.id for s in Statement.query.filter_by(discussion_id=discussion_id).all()]
        if statement_ids:
            StatementFlag.query.filter(StatementFlag.statement_id.in_(statement_ids)).delete(synchronize_session=False)
            Response.query.filter(Response.statement_id.in_(statement_ids)).delete(synchronize_session=False)
            StatementVote.query.filter(StatementVote.statement_id.in_(statement_ids)).delete(synchronize_session=False)
        
        # 3. Delete direct children of discussion
        Statement.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        StatementVote.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        DiscussionSourceArticle.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        DiscussionParticipant.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        DiscussionView.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        Notification.query.filter_by(discussion_id=discussion_id).delete(synchronize_session=False)
        
        # 4. Finally delete the discussion
        db.session.delete(discussion)
        db.session.commit()
        
        current_app.logger.info(f"Admin deleted discussion '{discussion_title}' (ID: {discussion_id})")
        flash('Discussion deleted successfully!', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error deleting discussion {discussion_id}: {str(e)}")
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
    search_query = request.args.get('q', '').strip()
    profile_filter = request.args.get('profile_type', '')
    
    # Build query with filters
    query = User.query
    
    # Search by username or email
    if search_query:
        search_term = f'%{search_query}%'
        query = query.filter(
            db.or_(
                User.username.ilike(search_term),
                User.email.ilike(search_term)
            )
        )
    
    # Filter by profile type
    if profile_filter:
        query = query.filter(User.profile_type == profile_filter)
    
    # Order and paginate
    users = query.order_by(User.created_at.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    # Get active subscription for each user
    from app.billing.service import get_active_subscription
    for user in users.items:
        user._cached_active_sub = get_active_subscription(user)
    
    return render_template(
        'admin/users/list.html', 
        users=users,
        search_query=search_query,
        profile_filter=profile_filter
    )

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

@admin_bp.route('/users/<int:user_id>/change-profile-type', methods=['POST'])
@login_required
@admin_required
def change_profile_type(user_id):
    """Change a user's profile type."""
    user = User.query.get_or_404(user_id)
    new_profile_type = request.form.get('profile_type', '').strip() or None
    
    valid_types = ['individual', 'company', None]
    if new_profile_type not in valid_types:
        flash('Invalid profile type.', 'error')
        return redirect(url_for('admin.list_users'))
    
    try:
        old_type = user.profile_type
        user.profile_type = new_profile_type
        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} changed user {user.username} profile type from {old_type} to {new_profile_type}")
        flash(f"Profile type for {user.username} changed to {new_profile_type or 'None'}.", 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error changing profile type: {str(e)}")
        flash('Error changing profile type. Please try again.', 'error')
    
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


@admin_bp.route('/users/<int:user_id>/subscription', methods=['GET', 'POST'])
@login_required
@admin_required
def manage_user_subscription(user_id):
    """
    Admin-only: Manually manage user subscriptions.
    Allows granting free access, changing plans, or revoking subscriptions.
    """
    user = User.query.get_or_404(user_id)
    
    # Get all pricing plans
    plans = PricingPlan.query.order_by(PricingPlan.price_monthly).all()
    
    # Get user's active subscription
    from app.billing.service import get_active_subscription
    active_sub = get_active_subscription(user)
    
    # Get all user's subscriptions (including inactive)
    all_subs = Subscription.query.filter_by(user_id=user.id).order_by(Subscription.created_at.desc()).all()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        try:
            if action == 'grant':
                # Grant new subscription
                plan_id = request.form.get('plan_id')
                subscription_type = request.form.get('subscription_type', 'free')  # 'free' or 'trial'
                
                if not plan_id:
                    flash('Please select a plan.', 'error')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                plan = PricingPlan.query.get(plan_id)
                if not plan:
                    flash('Invalid plan selected.', 'error')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                # CRITICAL: Check if user has active Stripe subscription
                if active_sub and active_sub.stripe_subscription_id:
                    flash(
                        f'⚠️ WARNING: User has ACTIVE STRIPE SUBSCRIPTION '
                        f'({active_sub.plan.name}, Stripe ID: {active_sub.stripe_subscription_id}). '
                        f'Granting manual access will NOT cancel their Stripe billing - they will continue to be charged! '
                        f'You must cancel their Stripe subscription manually via the Stripe Dashboard first, '
                        f'or the user will be double-billed.',
                        'error'
                    )
                    current_app.logger.warning(
                        f"Admin {current_user.username} attempted to grant manual subscription to user {user.username} "
                        f"who has active Stripe subscription {active_sub.stripe_subscription_id}"
                    )
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                # Cancel existing active subscription if any (only manual ones at this point)
                if active_sub:
                    active_sub.status = 'canceled'
                    active_sub.canceled_at = datetime.utcnow()
                
                # Create new manual subscription
                new_sub = Subscription(
                    user_id=user.id,
                    plan_id=plan.id,
                    status='active',  # Manually granted subscriptions are immediately active
                    stripe_subscription_id=None,  # No Stripe involvement for manual grants
                    stripe_customer_id=None,
                    billing_interval='lifetime' if subscription_type == 'free' else 'month',
                    created_at=datetime.utcnow(),
                    current_period_start=datetime.utcnow(),
                    current_period_end=None if subscription_type == 'free' else datetime.utcnow() + timedelta(days=30 if subscription_type == 'trial' else 365),
                    cancel_at_period_end=False
                )
                
                db.session.add(new_sub)
                db.session.commit()
                
                subscription_label = 'FREE ACCESS' if subscription_type == 'free' else '30-DAY TRIAL'
                current_app.logger.info(
                    f"Admin {current_user.username} granted {subscription_label} - {plan.name} plan to user {user.username} (ID: {user.id})"
                )
                flash(f'Successfully granted {subscription_label} to {plan.name} plan for {user.username}!', 'success')
            
            elif action == 'revoke':
                # Revoke active subscription
                if not active_sub:
                    flash('User has no active subscription to revoke.', 'warning')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                # CRITICAL: Warn if revoking Stripe subscription
                if active_sub.stripe_subscription_id:
                    flash(
                        f'⚠️ WARNING: This is a STRIPE SUBSCRIPTION (ID: {active_sub.stripe_subscription_id}). '
                        f'Revoking it here will NOT cancel billing in Stripe - the user will continue to be charged! '
                        f'You must cancel their subscription in the Stripe Dashboard to stop billing. '
                        f'Only proceed if you understand this will cause billing issues.',
                        'error'
                    )
                    current_app.logger.warning(
                        f"Admin {current_user.username} attempted to revoke Stripe subscription {active_sub.stripe_subscription_id} "
                        f"for user {user.username} - this will NOT stop Stripe billing!"
                    )
                    # Optionally: Block this action entirely
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                active_sub.status = 'canceled'
                active_sub.canceled_at = datetime.utcnow()
                db.session.commit()
                
                current_app.logger.info(
                    f"Admin {current_user.username} revoked subscription for user {user.username} (ID: {user.id})"
                )
                flash(f'Subscription revoked for {user.username}.', 'success')
            
            elif action == 'change':
                # Change plan of existing subscription
                plan_id = request.form.get('plan_id')
                
                if not active_sub:
                    flash('User has no active subscription to change.', 'error')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                if not plan_id:
                    flash('Please select a plan.', 'error')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                plan = PricingPlan.query.get(plan_id)
                if not plan:
                    flash('Invalid plan selected.', 'error')
                    return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
                
                old_plan = active_sub.plan
                active_sub.plan_id = plan.id
                db.session.commit()
                
                current_app.logger.info(
                    f"Admin {current_user.username} changed subscription for user {user.username} "
                    f"from {old_plan.name} to {plan.name}"
                )
                flash(f'Changed subscription from {old_plan.name} to {plan.name} for {user.username}.', 'success')
            
            else:
                flash('Invalid action.', 'error')
        
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error managing subscription for user {user_id}: {str(e)}")
            flash('Error managing subscription. Please try again.', 'error')
        
        return redirect(url_for('admin.manage_user_subscription', user_id=user_id))
    
    # GET request - show management page
    return render_template(
        'admin/users/manage_subscription.html',
        user=user,
        active_sub=active_sub,
        all_subs=all_subs,
        plans=plans
    )

@admin_bp.before_request
def log_admin_access():
    if current_user.is_authenticated and current_user.is_admin:
        current_app.logger.info(f"Admin access: {current_user.username} - {request.endpoint}")


@admin_bp.route('/daily-questions')
@login_required
@admin_required
def list_daily_questions():
    from sqlalchemy import func
    
    page = request.args.get('page', 1, type=int)
    per_page = 20
    
    # Get paginated questions
    questions = DailyQuestion.query.order_by(
        DailyQuestion.question_date.desc()
    ).paginate(page=page, per_page=per_page, error_out=False)
    
    # Batch fetch response counts for all questions on this page (prevents N+1)
    question_ids = [q.id for q in questions.items]
    response_counts = {}
    if question_ids:
        counts = db.session.query(
            DailyQuestionResponse.daily_question_id,
            func.count(DailyQuestionResponse.id)
        ).filter(
            DailyQuestionResponse.daily_question_id.in_(question_ids)
        ).group_by(DailyQuestionResponse.daily_question_id).all()
        response_counts = {qid: count for qid, count in counts}
    
    # Attach counts to question objects to avoid N+1 in template
    for q in questions.items:
        q._cached_response_count = response_counts.get(q.id, 0)
    
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
            if not question_date_str:
                flash('Question date is required', 'error')
                return redirect(url_for('admin.create_daily_question'))
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
                cold_start_threshold=int(request.form.get('cold_start_threshold') or 50),
                status=request.form.get('status', 'scheduled'),
                created_by_id=current_user.id
            )
            
            if question.status == 'published':
                question.published_at = datetime.utcnow()
            
            db.session.add(question)
            db.session.commit()
            
            flash(f'Daily question #{question.question_number} created successfully!', 'success')
            return redirect(url_for('admin.list_daily_questions'))
            
        except IntegrityError as e:
            db.session.rollback()
            error_str = str(e).lower()
            if 'question_date' in error_str or 'uq_daily_question_date' in error_str:
                flash(f'A question already exists for {question_date}. Another user may have created it.', 'error')
            elif 'question_number' in error_str:
                flash('Question number conflict. Please try again.', 'error')
            else:
                current_app.logger.error(f"Database integrity error creating daily question: {e}")
                flash('Database error creating daily question. Please try again.', 'error')
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
            question.cold_start_threshold = int(request.form.get('cold_start_threshold') or 50)
            
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
    # Get frequency filter from query params
    frequency_filter = request.args.get('frequency', '').lower()
    
    query = DailyQuestionSubscriber.query.options(
        joinedload(DailyQuestionSubscriber.user)
    )
    
    # Apply frequency filter if provided
    if frequency_filter in ['daily', 'weekly', 'monthly']:
        query = query.filter_by(email_frequency=frequency_filter)
    
    subscribers = query.order_by(
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
    
    # Count by frequency
    frequency_counts = {
        'daily': sum(1 for s in DailyQuestionSubscriber.query.filter_by(email_frequency='daily', is_active=True).all()),
        'weekly': sum(1 for s in DailyQuestionSubscriber.query.filter_by(email_frequency='weekly', is_active=True).all()),
        'monthly': sum(1 for s in DailyQuestionSubscriber.query.filter_by(email_frequency='monthly', is_active=True).all()),
    }
    
    return render_template(
        'admin/daily/subscribers.html',
        subscribers=subscribers,
        available_users=available_users,
        active_count=sum(1 for s in subscribers if s.is_active),
        total_count=len(subscribers),
        frequency_filter=frequency_filter,
        frequency_counts=frequency_counts
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


@admin_bp.route('/daily-questions/subscribers/<int:subscriber_id>/resend', methods=['POST'])
@login_required
@admin_required
def resend_daily_question(subscriber_id):
    """Resend today's daily question to a specific subscriber"""
    from app.resend_client import get_resend_client
    
    subscriber = DailyQuestionSubscriber.query.get_or_404(subscriber_id)
    
    # Get today's published question
    question = DailyQuestion.get_today()
    
    if not question:
        flash('No published daily question for today.', 'error')
        return redirect(url_for('admin.list_daily_subscribers'))
    
    if not subscriber.is_active:
        flash(f'Subscriber {subscriber.email} is not active.', 'warning')
        return redirect(url_for('admin.list_daily_subscribers'))
    
    try:
        # Ensure subscriber has a valid magic token
        if not subscriber.magic_token:
            subscriber.generate_magic_token()
            db.session.commit()
        
        client = get_resend_client()
        success = client.send_daily_question(subscriber, question)
        
        if success:
            # Update last_email_sent
            subscriber.last_email_sent = datetime.utcnow()
            db.session.commit()
            flash(f'Daily question resent to {subscriber.email}', 'success')
        else:
            flash(f'Failed to resend to {subscriber.email}. Check logs.', 'error')
    except Exception as e:
        current_app.logger.error(f"Resend daily question failed: {e}")
        flash(f'Error: {str(e)}', 'error')

    return redirect(url_for('admin.list_daily_subscribers'))


# ============================================================================
# FLAG MODERATION ROUTES
# ============================================================================

@admin_bp.route('/flags/statements')
@login_required
@admin_required
def list_statement_flags():
    """View all statement flags for admin review"""
    from sqlalchemy import func

    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status', 'pending')
    reason_filter = request.args.get('reason', None)

    # Build query
    query = StatementFlag.query.options(
        joinedload(StatementFlag.statement),
        joinedload(StatementFlag.flagger),
        joinedload(StatementFlag.reviewer)
    )

    # Apply filters
    if status_filter and status_filter != 'all':
        query = query.filter(StatementFlag.status == status_filter)

    if reason_filter and reason_filter != 'all':
        query = query.filter(StatementFlag.flag_reason == reason_filter)

    # Order by newest first
    query = query.order_by(StatementFlag.created_at.desc())

    # Paginate
    flags = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get counts for summary
    pending_count = StatementFlag.query.filter_by(status='pending').count()
    reviewed_count = StatementFlag.query.filter_by(status='reviewed').count()
    dismissed_count = StatementFlag.query.filter_by(status='dismissed').count()

    return render_template(
        'admin/flags/statement_flags.html',
        flags=flags,
        status_filter=status_filter,
        reason_filter=reason_filter,
        pending_count=pending_count,
        reviewed_count=reviewed_count,
        dismissed_count=dismissed_count
    )


@admin_bp.route('/flags/statements/<int:flag_id>/review', methods=['POST'])
@login_required
@admin_required
def review_statement_flag(flag_id):
    """Review a single statement flag"""
    flag = StatementFlag.query.get_or_404(flag_id)
    action = request.form.get('action')  # 'approve', 'dismiss'
    review_notes = request.form.get('review_notes', '')

    try:
        statement = flag.statement
        if not statement:
            flash('Statement no longer exists.', 'error')
            return redirect(url_for('admin.list_statement_flags'))

        if action == 'approve':
            flag.status = 'reviewed'
            statement.is_deleted = True
            statement.mod_status = -1  # Mark as rejected for consistency
            flash_msg = 'Flag approved and statement marked as deleted.'
        elif action == 'dismiss':
            flag.status = 'dismissed'
            flash_msg = 'Flag dismissed.'
        else:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin.list_statement_flags'))

        flag.reviewed_by_user_id = current_user.id
        flag.reviewed_at = datetime.utcnow()
        if review_notes:
            flag.additional_context = review_notes

        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} {action}ed statement flag {flag_id}")
        flash(flash_msg, 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error reviewing statement flag {flag_id}: {e}")
        flash('Error reviewing flag. Please try again.', 'error')

    return redirect(url_for('admin.list_statement_flags'))


@admin_bp.route('/flags/statements/bulk-review', methods=['POST'])
@login_required
@admin_required
def bulk_review_statement_flags():
    """Bulk review statement flags"""
    flag_ids = request.form.getlist('flag_ids')
    action = request.form.get('action')  # 'approve', 'dismiss'

    if not flag_ids:
        flash('No flags selected.', 'warning')
        return redirect(url_for('admin.list_statement_flags'))

    if action not in ['approve', 'dismiss']:
        flash('Invalid action.', 'error')
        return redirect(url_for('admin.list_statement_flags'))

    processed = 0
    skipped = 0
    try:
        for flag_id in flag_ids:
            flag = StatementFlag.query.get(int(flag_id))
            if not flag or flag.status != 'pending':
                skipped += 1
                continue

            statement = flag.statement
            if not statement:
                skipped += 1
                continue

            if action == 'approve':
                flag.status = 'reviewed'
                statement.is_deleted = True
                statement.mod_status = -1
            else:
                flag.status = 'dismissed'

            flag.reviewed_by_user_id = current_user.id
            flag.reviewed_at = datetime.utcnow()
            processed += 1

        db.session.commit()
        action_word = 'approved' if action == 'approve' else 'dismissed'

        msg_parts = [f'{processed} flag(s) {action_word}']
        if skipped > 0:
            msg_parts.append(f'{skipped} skipped (already reviewed or deleted)')

        flash('. '.join(msg_parts) + '.', 'success')
        current_app.logger.info(f"Admin {current_user.username} bulk {action_word} {processed} statement flags ({skipped} skipped)")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk reviewing statement flags: {e}")
        flash('Error processing flags. Please try again.', 'error')

    return redirect(url_for('admin.list_statement_flags'))


@admin_bp.route('/flags/responses')
@login_required
@admin_required
def list_response_flags():
    """View all daily question response flags for admin review"""
    from sqlalchemy import func

    page = request.args.get('page', 1, type=int)
    per_page = 20
    status_filter = request.args.get('status', 'pending')
    reason_filter = request.args.get('reason', None)

    # Build query
    query = DailyQuestionResponseFlag.query.options(
        joinedload(DailyQuestionResponseFlag.response).joinedload(DailyQuestionResponse.daily_question),
        joinedload(DailyQuestionResponseFlag.flagged_by),
        joinedload(DailyQuestionResponseFlag.reviewed_by)
    )

    # Apply filters
    if status_filter and status_filter != 'all':
        query = query.filter(DailyQuestionResponseFlag.status == status_filter)

    if reason_filter and reason_filter != 'all':
        query = query.filter(DailyQuestionResponseFlag.reason == reason_filter)

    # Order by newest first
    query = query.order_by(DailyQuestionResponseFlag.created_at.desc())

    # Paginate
    flags = query.paginate(page=page, per_page=per_page, error_out=False)

    # Get counts for summary
    pending_count = DailyQuestionResponseFlag.query.filter_by(status='pending').count()
    reviewed_valid_count = DailyQuestionResponseFlag.query.filter_by(status='reviewed_valid').count()
    reviewed_invalid_count = DailyQuestionResponseFlag.query.filter_by(status='reviewed_invalid').count()
    dismissed_count = DailyQuestionResponseFlag.query.filter_by(status='dismissed').count()

    return render_template(
        'admin/flags/response_flags.html',
        flags=flags,
        status_filter=status_filter,
        reason_filter=reason_filter,
        pending_count=pending_count,
        reviewed_valid_count=reviewed_valid_count,
        reviewed_invalid_count=reviewed_invalid_count,
        dismissed_count=dismissed_count
    )


@admin_bp.route('/flags/responses/<int:flag_id>/review', methods=['POST'])
@login_required
@admin_required
def review_response_flag(flag_id):
    """Review a single response flag and take action"""
    flag = DailyQuestionResponseFlag.query.get_or_404(flag_id)
    action = request.form.get('action')  # 'valid', 'invalid', 'dismiss'
    review_notes = request.form.get('review_notes', '')

    try:
        response = flag.response
        if not response:
            flash('Response no longer exists.', 'error')
            return redirect(url_for('admin.list_response_flags'))

        if action == 'valid':
            flag.status = 'reviewed_valid'
            response.is_hidden = True
            response.reviewed_by_admin = True
            response.reviewed_at = datetime.utcnow()
            response.reviewed_by_user_id = current_user.id
            flash_msg = 'Flag validated and response hidden.'
        elif action == 'invalid':
            flag.status = 'reviewed_invalid'

            # CRITICAL: Only restore if NO OTHER valid flags exist
            other_valid_flags = DailyQuestionResponseFlag.query.filter(
                DailyQuestionResponseFlag.response_id == response.id,
                DailyQuestionResponseFlag.id != flag_id,
                DailyQuestionResponseFlag.status.in_(['pending', 'reviewed_valid'])
            ).count()

            if other_valid_flags == 0:
                response.is_hidden = False
                flash_msg = 'Flag marked as invalid. Response restored.'
            else:
                flash_msg = f'Flag marked as invalid, but response remains hidden ({other_valid_flags} other flag(s) pending/valid).'

            response.reviewed_by_admin = True
            response.reviewed_at = datetime.utcnow()
            response.reviewed_by_user_id = current_user.id
        elif action == 'dismiss':
            flag.status = 'dismissed'
            flash_msg = 'Flag dismissed.'
        else:
            flash('Invalid action.', 'error')
            return redirect(url_for('admin.list_response_flags'))

        flag.reviewed_by_user_id = current_user.id
        flag.reviewed_at = datetime.utcnow()
        if review_notes:
            flag.review_notes = review_notes

        db.session.commit()
        current_app.logger.info(f"Admin {current_user.username} marked response flag {flag_id} as {action}")
        flash(flash_msg, 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error reviewing response flag {flag_id}: {e}")
        flash('Error reviewing flag. Please try again.', 'error')

    return redirect(url_for('admin.list_response_flags'))


@admin_bp.route('/flags/responses/bulk-review', methods=['POST'])
@login_required
@admin_required
def bulk_review_response_flags():
    """Bulk review response flags"""
    flag_ids = request.form.getlist('flag_ids')
    action = request.form.get('action')  # 'valid', 'invalid', 'dismiss'

    if not flag_ids:
        flash('No flags selected.', 'warning')
        return redirect(url_for('admin.list_response_flags'))

    if action not in ['valid', 'invalid', 'dismiss']:
        flash('Invalid action.', 'error')
        return redirect(url_for('admin.list_response_flags'))

    processed = 0
    skipped = 0
    try:
        for flag_id in flag_ids:
            flag = DailyQuestionResponseFlag.query.get(int(flag_id))
            if not flag or flag.status != 'pending':
                skipped += 1
                continue

            response = flag.response
            if not response:
                skipped += 1
                continue

            if action == 'valid':
                flag.status = 'reviewed_valid'
                response.is_hidden = True
                response.reviewed_by_admin = True
                response.reviewed_at = datetime.utcnow()
                response.reviewed_by_user_id = current_user.id
            elif action == 'invalid':
                flag.status = 'reviewed_invalid'

                # CRITICAL: Only restore if NO OTHER valid flags exist
                other_valid_flags = DailyQuestionResponseFlag.query.filter(
                    DailyQuestionResponseFlag.response_id == response.id,
                    DailyQuestionResponseFlag.id != flag.id,
                    DailyQuestionResponseFlag.status.in_(['pending', 'reviewed_valid'])
                ).count()

                if other_valid_flags == 0:
                    response.is_hidden = False

                response.reviewed_by_admin = True
                response.reviewed_at = datetime.utcnow()
                response.reviewed_by_user_id = current_user.id
            else:
                flag.status = 'dismissed'

            flag.reviewed_by_user_id = current_user.id
            flag.reviewed_at = datetime.utcnow()
            processed += 1

        db.session.commit()
        action_msg = {
            'valid': 'validated',
            'invalid': 'marked invalid',
            'dismiss': 'dismissed'
        }.get(action, 'processed')

        msg_parts = [f'{processed} flag(s) {action_msg}']
        if skipped > 0:
            msg_parts.append(f'{skipped} skipped (already reviewed or deleted)')

        flash('. '.join(msg_parts) + '.', 'success')
        current_app.logger.info(f"Admin {current_user.username} bulk {action_msg} {processed} response flags ({skipped} skipped)")
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"Error bulk reviewing response flags: {e}")
        flash('Error processing flags. Please try again.', 'error')

    return redirect(url_for('admin.list_response_flags'))


@admin_bp.route('/news-settings', methods=['GET', 'POST'])
@login_required
def news_settings():
    """
    Configure news transparency page quality thresholds.

    Allows admins to adjust:
    - Minimum civic score
    - Minimum quality score
    - Maximum sensationalism
    - Lookback hours (time range)
    """
    if not current_user.is_admin:
        flash('Admin access required', 'error')
        return redirect(url_for('main.index'))

    from app.models import AdminSettings
    from app.news.selector import NewsPageSelector, get_topic_leaning
    from app.brief.coverage_analyzer import CoverageAnalyzer

    if request.method == 'POST':
        try:
            def safe_float(value, default):
                if value is None:
                    return default
                if str(value).strip().lower() == 'nan':
                    raise ValueError("NaN is not a valid value")
                return float(value)

            settings = {
                'min_civic_score': safe_float(request.form.get('min_civic_score'), 0.5),
                'min_quality_score': safe_float(request.form.get('min_quality_score'), 0.4),
                'max_sensationalism': safe_float(request.form.get('max_sensationalism'), 0.8),
                'lookback_hours': int(request.form.get('lookback_hours') or 24)
            }

            # Validate ranges
            if not (0 <= settings['min_civic_score'] <= 1):
                flash('Civic score must be between 0 and 1', 'error')
                return redirect(url_for('admin.news_settings'))

            if not (0 <= settings['min_quality_score'] <= 1):
                flash('Quality score must be between 0 and 1', 'error')
                return redirect(url_for('admin.news_settings'))

            if not (0 <= settings['max_sensationalism'] <= 1):
                flash('Sensationalism must be between 0 and 1', 'error')
                return redirect(url_for('admin.news_settings'))

            if not (1 <= settings['lookback_hours'] <= 168):  # 1 hour to 1 week
                flash('Lookback hours must be between 1 and 168', 'error')
                return redirect(url_for('admin.news_settings'))

            AdminSettings.set('news_page_thresholds', settings, current_user.id)
            flash('News page settings updated successfully', 'success')
            current_app.logger.info(f"Admin {current_user.username} updated news page settings: {settings}")

        except ValueError as e:
            flash(f'Invalid value: {e}', 'error')
        except Exception as e:
            current_app.logger.error(f"Error updating news settings: {e}")
            flash('Error updating settings. Please try again.', 'error')

        return redirect(url_for('admin.news_settings'))

    # GET request - load current settings and stats
    selector = NewsPageSelector()
    settings = selector.get_current_settings()

    # Get preview stats
    try:
        topics = selector.select_topics()

        # Calculate statistics
        left_count = sum(1 for t in topics if get_topic_leaning(t) == 'left')
        center_count = sum(1 for t in topics if get_topic_leaning(t) == 'center')
        right_count = sum(1 for t in topics if get_topic_leaning(t) == 'right')

        avg_civic = sum(t.civic_score for t in topics) / len(topics) if topics else 0
        avg_quality = sum(t.quality_score for t in topics) / len(topics) if topics else 0

        stats = {
            'total_topics': len(topics),
            'left_count': left_count,
            'center_count': center_count,
            'right_count': right_count,
            'avg_civic_score': round(avg_civic, 2),
            'avg_quality_score': round(avg_quality, 2)
        }

    except Exception as e:
        current_app.logger.error(f"Error loading news stats: {e}")
        stats = {
            'total_topics': 0,
            'left_count': 0,
            'center_count': 0,
            'right_count': 0,
            'avg_civic_score': 0,
            'avg_quality_score': 0
        }

    return render_template(
        'admin/news_settings.html',
        settings=settings,
        stats=stats
    )


# =============================================================================
# Source Claim Management
# =============================================================================

@admin_bp.route('/sources/claims')
@login_required
@admin_required
def source_claims():
    """View and manage pending source claims."""
    # Get pending claims
    pending_claims = NewsSource.query.filter(
        NewsSource.claim_status == 'pending'
    ).order_by(NewsSource.claim_requested_at.desc()).all()

    # Get recently processed claims (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    recent_claims = NewsSource.query.filter(
        NewsSource.claim_status.in_(['approved', 'rejected']),
        NewsSource.claimed_at >= thirty_days_ago
    ).order_by(NewsSource.claimed_at.desc()).limit(20).all()

    return render_template(
        'admin/sources/claims.html',
        pending_claims=pending_claims,
        recent_claims=recent_claims
    )


@admin_bp.route('/sources/claims/<int:source_id>/approve', methods=['POST'])
@login_required
@admin_required
def approve_source_claim(source_id):
    """Approve a source claim request."""
    source = NewsSource.query.get_or_404(source_id)

    if source.claim_status != 'pending':
        flash('This claim is not pending review.', 'error')
        return redirect(url_for('admin.source_claims'))

    if not source.claim_requested_by:
        flash('No user associated with this claim request.', 'error')
        return redirect(url_for('admin.source_claims'))

    # Get the requesting user's company profile
    requesting_user = source.claim_requested_by
    if not requesting_user.company_profile:
        flash('The requesting user no longer has a company profile.', 'error')
        source.claim_status = 'unclaimed'
        source.claim_requested_by_id = None
        source.claim_requested_at = None
        db.session.commit()
        return redirect(url_for('admin.source_claims'))

    # Approve the claim
    source.claim_status = 'approved'
    source.claimed_by_profile_id = requesting_user.company_profile.id
    source.claimed_at = datetime.utcnow()

    try:
        db.session.commit()
        current_app.logger.info(
            f'Source claim approved: {source.name} -> {requesting_user.company_profile.company_name}'
        )
        flash(f'Claim for "{source.name}" has been approved.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error approving claim: {str(e)}')
        flash('An error occurred while approving the claim.', 'error')

    return redirect(url_for('admin.source_claims'))


@admin_bp.route('/sources/claims/<int:source_id>/reject', methods=['POST'])
@login_required
@admin_required
def reject_source_claim(source_id):
    """Reject a source claim request."""
    source = NewsSource.query.get_or_404(source_id)

    if source.claim_status != 'pending':
        flash('This claim is not pending review.', 'error')
        return redirect(url_for('admin.source_claims'))

    # Reject the claim
    source.claim_status = 'rejected'
    source.claim_requested_by_id = None
    source.claim_requested_at = None

    try:
        db.session.commit()
        current_app.logger.info(f'Source claim rejected: {source.name}')
        flash(f'Claim for "{source.name}" has been rejected.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error rejecting claim: {str(e)}')
        flash('An error occurred while rejecting the claim.', 'error')

    return redirect(url_for('admin.source_claims'))


@admin_bp.route('/sources/claims/<int:source_id>/revoke', methods=['POST'])
@login_required
@admin_required
def revoke_source_claim(source_id):
    """Revoke an approved source claim."""
    source = NewsSource.query.get_or_404(source_id)

    if source.claim_status != 'approved':
        flash('This source is not currently claimed.', 'error')
        return redirect(url_for('admin.source_claims'))

    # Revoke the claim
    source.claim_status = 'unclaimed'
    source.claimed_by_profile_id = None
    source.claimed_at = None
    source.claim_requested_by_id = None
    source.claim_requested_at = None

    try:
        db.session.commit()
        current_app.logger.info(f'Source claim revoked: {source.name}')
        flash(f'Claim for "{source.name}" has been revoked.', 'success')
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f'Error revoking claim: {str(e)}')
        flash('An error occurred while revoking the claim.', 'error')

    return redirect(url_for('admin.source_claims'))
