# app/profiles/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, current_app, abort, make_response
from flask_login import login_required, current_user
from app import db
from app.models import IndividualProfile, CompanyProfile, Discussion, Programme, generate_unique_slug
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from replit.object_storage import Client
from werkzeug.utils import secure_filename
from werkzeug.datastructures import FileStorage
from app.storage_utils import (
    delete_from_object_storage,
    get_recent_activity,
    upload_to_object_storage,
)
from app.middleware import track_profile_view


import io
from app.lib.url_utils import safe_next_url as _safe_next_url
from flask_babel import gettext as _

from app.profiles.helpers import apply_form_to_profile

profiles_bp = Blueprint('profiles', __name__, template_folder='../templates/profiles')

client = Client()



@profiles_bp.route('/get-image/<path:filename>')
def get_image(filename):
    """Retrieve image from Replit's object storage"""
    try:
        # Validate filename to prevent path traversal
        if '..' in filename or filename.startswith('/'):
            current_app.logger.warning(f"Blocked potential path traversal attempt: {filename}")
            return send_file('static/images/default-avatar.png', mimetype='image/png')
        
        storage_path = f"profile_images/{filename}"

        # Download the file data as bytes
        file_data = client.download_as_bytes(storage_path)

        if file_data:
            file_like = io.BytesIO(file_data)

            # Determine MIME type based on file extension
            mime_type = 'image/jpeg'
            if filename.lower().endswith('.png'):
                mime_type = 'image/png'
            elif filename.lower().endswith('.gif'):
                mime_type = 'image/gif'
            elif filename.lower().endswith('.svg'):
                mime_type = 'image/svg+xml'
            elif filename.lower().endswith('.webp'):
                mime_type = 'image/webp'

            return send_file(file_like, mimetype=mime_type, as_attachment=False, download_name=filename)

        current_app.logger.error(f"Image not found: {filename}")
        return send_file('static/images/default-avatar.png', mimetype='image/png')

    except Exception as e:
        current_app.logger.error(f"Error retrieving image {filename}: {str(e)}")
        if 'banner' in filename:
            return send_file('static/images/default-banner.jpg', mimetype='image/jpeg')
        return send_file('static/images/default-avatar.png', mimetype='image/png')


@profiles_bp.route('/assets/<path:filename>')
def get_static_asset(filename):
    """Serve static assets (hero, speakers) from Replit Object Storage.
    
    This avoids disk I/O errors (OSError [Errno 5]) by reading from object storage
    instead of the app's filesystem. Assets are cached for 1 hour.
    """
    try:
        if '..' in filename or filename.startswith('/'):
            current_app.logger.warning(f"Blocked path traversal: {filename}")
            abort(404)
        
        storage_path = f"static_assets/{filename}"
        file_data = client.download_as_bytes(storage_path)
        
        if file_data:
            file_like = io.BytesIO(file_data)
            
            mime_type = 'image/jpeg'
            lower_filename = filename.lower()
            if lower_filename.endswith('.png'):
                mime_type = 'image/png'
            elif lower_filename.endswith('.gif'):
                mime_type = 'image/gif'
            elif lower_filename.endswith('.webp'):
                mime_type = 'image/webp'
            elif lower_filename.endswith('.svg'):
                mime_type = 'image/svg+xml'
            
            response = make_response(send_file(file_like, mimetype=mime_type, as_attachment=False, download_name=filename.split('/')[-1]))
            response.headers['Cache-Control'] = 'public, max-age=3600'
            return response
        
        current_app.logger.warning(f"Asset not found in storage: {filename}")
        abort(404)
        
    except Exception as e:
        current_app.logger.error(f"Error serving asset {filename}: {str(e)}")
        abort(404)


# Function to SELECT an individual or company profile page to create
@profiles_bp.route('/profile/select')
@login_required
def select_profile_type():
    return render_template(
        'profiles/select_profile_type.html',
        next_url=_safe_next_url(request.args.get('next')),
    )


@profiles_bp.route('/profile/individual/new', methods=['GET', 'POST'])
@login_required
def create_individual_profile():
    form = IndividualProfileForm()
    next_url = _safe_next_url(request.form.get('next') or request.args.get('next'))
    if request.method == 'GET' and not form.email.data:
        form.email.data = current_user.email
    if form.validate_on_submit():
        profile_image = None
        banner_image = None
        try:
            if form.profile_image.data:
                profile_image = upload_to_object_storage(
                    form.profile_image.data,
                    secure_filename(form.profile_image.data.filename),
                    user_id=current_user.id,
                )
                if profile_image is None:
                    flash(_("Profile picture couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB). Your profile was saved without it."), "warning")

            if form.banner_image.data:
                banner_image = upload_to_object_storage(
                    form.banner_image.data,
                    secure_filename(form.banner_image.data.filename),
                    user_id=current_user.id,
                )
                if banner_image is None:
                    flash(_("Banner image couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB). Your profile was saved without it."), "warning")

            profile = IndividualProfile(
                user_id=current_user.id,
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
                tiktok_url=form.tiktok_url.data,
                bluesky_url=form.bluesky_url.data,
                slug=generate_unique_slug(IndividualProfile, form.full_name.data, fallback='profile'),
            )

            current_user.profile_type = 'individual'

            db.session.add(profile)
            db.session.commit()

            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    posthog.capture(
                        distinct_id=str(current_user.id),
                        event='profile_created',
                        properties={
                            'profile_type': 'individual',
                            'profile_id': profile.id,
                            'profile_slug': profile.slug,
                        }
                    )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")

            flash(_("Profile created! You're all set — start a discussion or create a programme from your dashboard."), "success")
            return redirect(next_url or url_for('auth.dashboard'))

        except Exception as e:
            db.session.rollback()
            # Don't leak orphaned images in object storage when the DB step fails.
            for uploaded in (profile_image, banner_image):
                if uploaded:
                    try:
                        delete_from_object_storage(uploaded)
                    except Exception:
                        pass
            current_app.logger.error(f"Error creating profile: {str(e)}")
            flash(_("Error creating profile. Please try again."), "error")
            return render_template('profiles/create_individual_profile.html', form=form, next_url=next_url)

    return render_template('profiles/create_individual_profile.html', form=form, next_url=next_url)


@profiles_bp.route('/profile/company/new', methods=['GET', 'POST'])
@login_required
def create_company_profile():
    form = CompanyProfileForm()
    next_url = _safe_next_url(request.form.get('next') or request.args.get('next'))
    if form.validate_on_submit():
        logo = None
        banner_image = None
        try:
            if form.logo.data:
                logo = upload_to_object_storage(
                    form.logo.data,
                    secure_filename(form.logo.data.filename),
                    user_id=current_user.id,
                )
                if logo is None:
                    flash(_("Logo couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB). Your profile was saved without it."), "warning")

            if form.banner_image.data:
                banner_image = upload_to_object_storage(
                    form.banner_image.data,
                    secure_filename(form.banner_image.data.filename),
                    user_id=current_user.id,
                )
                if banner_image is None:
                    flash(_("Banner image couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB). Your profile was saved without it."), "warning")

            profile = CompanyProfile(
                user_id=current_user.id,
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
                tiktok_url=form.tiktok_url.data,
                bluesky_url=form.bluesky_url.data,
                slug=generate_unique_slug(CompanyProfile, form.company_name.data, fallback='company'),
            )

            current_user.profile_type = 'company'
            db.session.add(profile)
            db.session.commit()

            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    posthog.capture(
                        distinct_id=str(current_user.id),
                        event='profile_created',
                        properties={
                            'profile_type': 'company',
                            'profile_id': profile.id,
                            'profile_slug': profile.slug,
                        }
                    )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")

            flash(_("Profile created! You're all set — start a discussion or create a programme from your dashboard."), "success")
            return redirect(next_url or url_for('auth.dashboard'))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating company profile: {str(e)}")
            if logo:
                try:
                    delete_from_object_storage(logo)
                except Exception:
                    pass
            if banner_image:
                try:
                    delete_from_object_storage(banner_image)
                except Exception:
                    pass
            flash(_("Error creating company profile. Please try again."), "error")
            return render_template('profiles/create_company_profile.html', form=form, next_url=next_url)

    return render_template('profiles/create_company_profile.html', form=form, next_url=next_url)




#routes to edit individual and company profiles once created.
# Change from profile_id parameter to username
@profiles_bp.route('/profile/individual/<username>/edit', methods=['GET', 'POST'])
@login_required
def edit_individual_profile(username):
    profile = IndividualProfile.query.filter_by(slug=username).first_or_404()
    if profile.user_id != current_user.id:
        flash(_("You do not have permission to edit this profile."), "error")
        return redirect(url_for('main.index'))

    form = IndividualProfileForm(obj=profile)
    form.submit.label.text = 'Save Changes'

    if form.validate_on_submit():
        try:
            
            if form.profile_image.data and isinstance(form.profile_image.data, FileStorage):
                uploaded = upload_to_object_storage(
                    form.profile_image.data,
                    secure_filename(form.profile_image.data.filename),
                    user_id=current_user.id,
                )
                if uploaded is None:
                    flash(_("New profile picture couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB); the existing one was kept."), "warning")
                else:
                    profile.profile_image = uploaded

            if form.banner_image.data and isinstance(form.banner_image.data, FileStorage):
                uploaded = upload_to_object_storage(
                    form.banner_image.data,
                    secure_filename(form.banner_image.data.filename),
                    user_id=current_user.id,
                )
                if uploaded is None:
                    flash(_("New banner image couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB); the existing one was kept."), "warning")
                else:
                    profile.banner_image = uploaded

            apply_form_to_profile(profile, form)

            # Update slug if name changed
            profile.update_slug()

            db.session.commit()

            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    posthog.capture(
                        distinct_id=str(current_user.id),
                        event='profile_edited',
                        properties={
                            'profile_type': 'individual',
                            'profile_id': profile.id,
                            'profile_slug': profile.slug,
                        }
                    )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")

            flash(_("Profile updated successfully!"), "success")
            return redirect(url_for('profiles.view_individual_profile', username=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile: {str(e)}")
            flash(_("Error updating profile. Please try again."), "error")

    return render_template('profiles/edit_individual_profile.html', form=form, profile=profile)

# Similarly for company profiles
@profiles_bp.route('/profile/company/<company_name>/edit', methods=['GET', 'POST'])
@login_required
def edit_company_profile(company_name):
    profile = CompanyProfile.query.filter_by(slug=company_name).first_or_404()
    if profile.user_id != current_user.id:
        flash(_("You do not have permission to edit this profile."), "error")
        return redirect(url_for('main.index'))

    form = CompanyProfileForm(obj=profile)
    form.submit.label.text = 'Save Changes'

    if form.validate_on_submit():
        try:
            if form.logo.data and isinstance(form.logo.data, FileStorage):
                uploaded = upload_to_object_storage(
                    form.logo.data,
                    secure_filename(form.logo.data.filename),
                    user_id=current_user.id,
                )
                if uploaded is None:
                    flash(_("New logo couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB); the existing one was kept."), "warning")
                else:
                    profile.logo = uploaded

            if form.banner_image.data and isinstance(form.banner_image.data, FileStorage):
                uploaded = upload_to_object_storage(
                    form.banner_image.data,
                    secure_filename(form.banner_image.data.filename),
                    user_id=current_user.id,
                )
                if uploaded is None:
                    flash(_("New banner image couldn't be uploaded (must be JPG, PNG, GIF or WEBP under 5MB); the existing one was kept."), "warning")
                else:
                    profile.banner_image = uploaded

            apply_form_to_profile(profile, form)

            # Update slug if name changed
            profile.update_slug()

            db.session.commit()

            try:
                import posthog
                if posthog and getattr(posthog, 'project_api_key', None):
                    posthog.capture(
                        distinct_id=str(current_user.id),
                        event='profile_edited',
                        properties={
                            'profile_type': 'company',
                            'profile_id': profile.id,
                            'profile_slug': profile.slug,
                        }
                    )
            except Exception as e:
                current_app.logger.warning(f"PostHog tracking error: {e}")

            flash(_("Company profile updated successfully!"), "success")
            return redirect(url_for('profiles.view_company_profile', company_name=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating company profile: {str(e)}")
            flash(_("Error updating profile. Please try again."), "error")

    return render_template('profiles/edit_company_profile.html', form=form, profile=profile)





@profiles_bp.route('/profile/individual/<username>')
@track_profile_view  # Add this decorator
def view_individual_profile(username):
    profile = IndividualProfile.query.filter_by(slug=username).first_or_404()
    page = request.args.get('page', 1, type=int)
    discussions = Discussion.query.filter_by(creator_id=profile.user_id).order_by(
        Discussion.created_at.desc()
    ).paginate(page=page, per_page=10, error_out=False)
    return render_template('profiles/individual_profile.html', profile=profile, discussions=discussions)

@profiles_bp.route('/profile/company/<company_name>')
@track_profile_view  # Add this decorator
def view_company_profile(company_name):
    profile = CompanyProfile.query.filter_by(slug=company_name).first_or_404()
    page = request.args.get('page', 1, type=int)
    discussions = Discussion.query.filter_by(creator_id=profile.user_id).order_by(
        Discussion.created_at.desc()
    ).paginate(page=page, per_page=10, error_out=False)
    programmes = Programme.query.filter_by(
        company_profile_id=profile.id,
        visibility='public',
        status='active'
    ).order_by(Programme.created_at.desc()).all()
    return render_template('profiles/company_profile.html', profile=profile, discussions=discussions, programmes=programmes)


#Unified view_profile Route (This is the new route that acts as the primary link):
@profiles_bp.route('/profile/<username>')
@login_required
def view_profile(username):
    individual = IndividualProfile.query.filter_by(slug=username).first()
    if individual:
        return redirect(url_for('profiles.view_individual_profile', username=username))
    
    company = CompanyProfile.query.filter_by(slug=username).first()
    if company:
        return redirect(url_for('profiles.view_company_profile', company_name=username))

    flash(_("Profile not found."), "error")
    return redirect(url_for('main.index'))

