# app/profiles/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file, current_app
from flask_login import login_required, current_user
from app import db
from app.models import IndividualProfile, CompanyProfile, Discussion
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from replit.object_storage import Client
from werkzeug.utils import secure_filename

import os
import json
import time
import io


profiles_bp = Blueprint('profiles', __name__, template_folder='../templates/profiles')

client = Client()



def upload_to_object_storage(file_data, filename):
    """Upload file to Replit's object storage"""
    try:
        unique_filename = f"{current_user.id}_{int(time.time())}_{filename}"
        storage_path = f"profile_images/{unique_filename}"

        # Read file data
        file_content = file_data.read()

        # Upload file content as bytes
        client.upload_from_bytes(storage_path, file_content)

        current_app.logger.info(f"Successfully uploaded {filename} to object storage")
        return unique_filename

    except Exception as e:
        current_app.logger.error(f"Error uploading file: {str(e)}")
        return None


def delete_from_object_storage(filename):
    """Delete a file from Replit's object storage"""
    try:
        storage_path = f"profile_images/{filename}"
        client.delete(storage_path)
        current_app.logger.info(f"Successfully deleted {filename} from object storage")
        return True

    except Exception as e:
        current_app.logger.error(f"Error deleting {filename} from object storage: {str(e)}")
        return False



@profiles_bp.route('/get-image/<path:filename>')
def get_image(filename):
    """Retrieve image from Replit's object storage"""
    try:
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

            return send_file(file_like, mimetype=mime_type, as_attachment=False, download_name=filename)

        current_app.logger.error(f"Image not found: {filename}")
        return send_file('static/images/default-avatar.png', mimetype='image/png')

    except Exception as e:
        current_app.logger.error(f"Error retrieving image {filename}: {str(e)}")
        if 'banner' in filename:
            return send_file('static/images/default-banner.png', mimetype='image/png')
        return send_file('static/images/default-avatar.png', mimetype='image/png')



# Function to SELECT an individual or company profile page to create
@profiles_bp.route('/profile/select')
@login_required
def select_profile_type():
    return render_template('profiles/select_profile_type.html')


@profiles_bp.route('/profile/individual/new', methods=['GET', 'POST'])
@login_required
def create_individual_profile():
    form = IndividualProfileForm()
    if form.validate_on_submit():
        try:
            profile_image = None
            banner_image = None

            # Handle file uploads
            if form.profile_image.data:
                profile_image_file = form.profile_image.data
                profile_image = secure_filename(profile_image_file.filename)
                profile_image = f"{current_user.id}_{int(time.time())}_{profile_image}"
                upload_to_object_storage(profile_image_file, profile_image)

            if form.banner_image.data:
                banner_image_file = form.banner_image.data
                banner_image = secure_filename(banner_image_file.filename)
                banner_image = f"{current_user.id}_{int(time.time())}_{banner_image}"
                upload_to_object_storage(banner_image_file, banner_image)

            # Process social links
            social_links = {}
            for key in request.form:
                if key.startswith('social_links['):
                    platform = key[13:-1]  # Extract name between brackets
                    if request.form[key].strip():  # Only add non-empty values
                        social_links[platform] = request.form[key].strip()

            # Create profile
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
                social_links=social_links
            )

            # Update user's profile type
            current_user.profile_type = 'individual'

            db.session.add(profile)
            db.session.commit()

            flash("Individual profile created successfully!", "success")
            return redirect(url_for('profiles.view_individual_profile', username=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating profile: {str(e)}")
            flash("Error creating profile. Please try again.", "error")
            return render_template('profiles/create_individual_profile.html', form=form)

    return render_template('profiles/create_individual_profile.html', form=form)


@profiles_bp.route('/profile/company/new', methods=['GET', 'POST'])
@login_required
def create_company_profile():
    form = CompanyProfileForm()
    if form.validate_on_submit():
        try:
            profile_image = None
            banner_image = None

            # Handle file uploads
            if form.profile_image.data:
                profile_image_file = form.profile_image.data
                profile_image = secure_filename(profile_image_file.filename)
                profile_image = f"{current_user.id}_{int(time.time())}_logo_{profile_image}"
                upload_to_object_storage(profile_image_file, profile_image)

            if form.banner_image.data:
                banner_image_file = form.banner_image.data
                banner_image = secure_filename(banner_image_file.filename)
                banner_image = f"{current_user.id}_{int(time.time())}_banner_{banner_image}"
                upload_to_object_storage(banner_image_file, banner_image)

            # Process social links
            social_links = {}
            for key in request.form:
                if key.startswith('social_links['):
                    platform = key[13:-1]  # Extract name between brackets
                    if request.form[key].strip():  # Only add non-empty values
                        social_links[platform] = request.form[key].strip()

            # Create profile
            profile = CompanyProfile(
                user_id=current_user.id,
                company_name=form.company_name.data,
                description=form.description.data,
                profile_image=profile_image,
                banner_image=banner_image,
                city=form.city.data,
                country=form.country.data,
                email=form.email.data,
                website=form.website.data,
                social_links=social_links
            )

            # Update user's profile type
            current_user.profile_type = 'company'

            db.session.add(profile)
            db.session.commit()

            flash("Company profile created successfully!", "success")
            return redirect(url_for('profiles.view_company_profile', company_name=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error creating company profile: {str(e)}")
            # Clean up any uploaded files if there was an error
            if profile_image:
                try:
                    delete_from_object_storage(profile_image)
                except:
                    pass
            if banner_image:
                try:
                    delete_from_object_storage(banner_image)
                except:
                    pass
            flash("Error creating company profile. Please try again.", "error")
            return render_template('profiles/create_company_profile.html', form=form)

    return render_template('profiles/create_company_profile.html', form=form)


#routes to edit individual and company profiles once created.
@profiles_bp.route('/profile/individual/edit/<int:profile_id>', methods=['GET', 'POST'])
@login_required
def edit_individual_profile(profile_id):
    profile = IndividualProfile.query.get_or_404(profile_id)
    if profile.user_id != current_user.id:
        flash("You do not have permission to edit this profile.", "error")
        return redirect(url_for('main.index'))

    form = IndividualProfileForm(obj=profile)

    if form.validate_on_submit():
        try:
            # Update profile fields
            profile.full_name = form.full_name.data
            profile.bio = form.bio.data
            profile.city = form.city.data
            profile.country = form.country.data
            profile.email = form.email.data
            profile.website = form.website.data
            profile.social_links = {
                key[13:-1]: request.form[key].strip()
                for key in request.form if key.startswith('social_links[') and request.form[key].strip()
            }

            # Handle file updates
            if form.profile_image.data:
                profile_image_file = form.profile_image.data
                profile_image = upload_to_object_storage(profile_image_file, profile.profile_image)
                profile.profile_image = profile_image

            if form.banner_image.data:
                banner_image_file = form.banner_image.data
                banner_image = upload_to_object_storage(banner_image_file, profile.banner_image)
                profile.banner_image = banner_image

            db.session.commit()
            flash("Profile updated successfully!", "success")
            return redirect(url_for('profiles.view_individual_profile', username=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile: {str(e)}")
            flash("Error updating profile. Please try again.", "error")

    return render_template('profiles/edit_individual_profile.html', form=form, profile=profile)


@profiles_bp.route('/profile/company/edit/<int:profile_id>', methods=['GET', 'POST'])
@login_required
def edit_company_profile(profile_id):
    profile = CompanyProfile.query.get_or_404(profile_id)
    if profile.user_id != current_user.id:
        flash("You do not have permission to edit this profile.", "error")
        return redirect(url_for('main.index'))

    form = CompanyProfileForm(obj=profile)

    if form.validate_on_submit():
        try:
            # Update profile fields
            profile.company_name = form.company_name.data
            profile.description = form.description.data
            profile.city = form.city.data
            profile.country = form.country.data
            profile.email = form.email.data
            profile.website = form.website.data
            profile.social_links = {
                key[13:-1]: request.form[key].strip()
                for key in request.form if key.startswith('social_links[') and request.form[key].strip()
            }

            # Handle file updates
            if form.profile_image.data:
                profile_image_file = form.profile_image.data
                profile_image = upload_to_object_storage(profile_image_file, profile.profile_image)
                profile.profile_image = profile_image

            if form.banner_image.data:
                banner_image_file = form.banner_image.data
                banner_image = upload_to_object_storage(banner_image_file, profile.banner_image)
                profile.banner_image = banner_image

            db.session.commit()
            flash("Company profile updated successfully!", "success")
            return redirect(url_for('profiles.view_company_profile', company_name=profile.slug))

        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error updating profile: {str(e)}")
            flash("Error updating profile. Please try again.", "error")

    return render_template('profiles/edit_company_profile.html', form=form, profile=profile)







@profiles_bp.route('/profile/individual/<username>')
def view_individual_profile(username):
    profile = IndividualProfile.query.filter_by(slug=username).first_or_404()
    discussions = Discussion.query.filter_by(creator_id=profile.user_id).all()
    return render_template('profiles/individual_profile.html', profile=profile, discussions=discussions)


@profiles_bp.route('/profile/company/<company_name>')
def view_company_profile(company_name):
    profile = CompanyProfile.query.filter_by(slug=company_name).first_or_404()
    discussions = Discussion.query.filter_by(creator_id=profile.user_id).all()
    return render_template('profiles/company_profile.html', profile=profile, discussions=discussions)


#Unified view_profile Route (This is the new route that acts as the primary link):
@profiles_bp.route('/profile/<username>')
@login_required
def view_profile(username):
    profile = IndividualProfile.query.filter_by(slug=username).first() or CompanyProfile.query.filter_by(slug=username).first()
    if profile:
        discussions = Discussion.query.filter_by(creator_id=profile.user_id).all()
        return render_template('profiles/view_profile.html', profile=profile, discussions=discussions)

    flash("Profile not found.", "error")
    return redirect(url_for('main.index'))

