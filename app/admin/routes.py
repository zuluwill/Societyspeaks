# app/admin/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, IndividualProfile, CompanyProfile, Discussion
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from app.admin.forms import UserAssignmentForm
from functools import wraps
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
    individual_profiles = IndividualProfile.query.all()
    company_profiles = CompanyProfile.query.all()
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
    discussions = Discussion.query.order_by(Discussion.created_at.desc()).all()
    return render_template('admin/discussions/list.html', discussions=discussions)

@admin_bp.route('/users')
@login_required
@admin_required
def list_users():
    users = User.query.order_by(User.created_at.desc()).all()
    return render_template('admin/users/list.html', users=users)

@admin_bp.before_request
def log_admin_access():
    if current_user.is_authenticated and current_user.is_admin:
        current_app.logger.info(f"Admin access: {current_user.username} - {request.endpoint}")
