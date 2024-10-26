# app/profiles/routes.py
from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from app import db
from app.models import IndividualProfile, CompanyProfile, Discussion
from app.profiles.forms import IndividualProfileForm, CompanyProfileForm
from replit.object_storage import Client

import os

profiles_bp = Blueprint('profiles', __name__, template_folder='../templates/profiles')

client = Client()


# Function to upload a file to Replit object storage
def upload_to_object_storage(file_data, filename):
    # Upload file data as bytes
    client.upload_from_bytes(f"profile_images/{filename}", file_data.read())
    return f"profile_images/{filename}"

@profiles_bp.route('/get-image/<filename>')
def get_image(filename):
    file_data = client.download_as_bytes(f"profile_images/{filename}")
    if file_data:
        return send_file(io.BytesIO(file_data), mimetype='image/jpeg')  # Return as image response
    else:
        return "File not found", 404



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
        profile_image = None
        banner_image = None

        # Handle file uploads via Replit Object Storage
        if 'profile_image' in request.files:
            profile_image_file = request.files['profile_image']
            profile_image = profile_image_file.filename
            upload_to_object_storage(profile_image_file, profile_image)

        if 'banner_image' in request.files:
            banner_image_file = request.files['banner_image']
            banner_image = banner_image_file.filename
            upload_to_object_storage(banner_image_file, banner_image)

        # Creating the individual profile entry
        profile = IndividualProfile(
            user_id=current_user.id,
            full_name=form.full_name.data,
            bio=form.bio.data,
            profile_image=profile_image,
            banner_image=banner_image,
            location=form.location.data,
            email=form.email.data,
            website=form.website.data,
            social_links=form.social_links.data  # Ensure it's in a compatible format for JSON
        )

        db.session.add(profile)
        db.session.commit()
        flash("Individual profile created!", "success")
        return redirect(url_for('profiles.view_individual_profile', username=profile.slug))

    return render_template('profiles/create_individual_profile.html', form=form)



@profiles_bp.route('/profile/company/new', methods=['GET', 'POST'])
@login_required
def create_company_profile():
    form = CompanyProfileForm()
    if form.validate_on_submit():
        profile_image = None
        banner_image = None

        # Handle file uploads via Replit Object Storage
        if 'profile_image' in request.files:
            profile_image_file = request.files['profile_image']
            profile_image = profile_image_file.filename
            upload_to_object_storage(profile_image_file, profile_image)

        if 'banner_image' in request.files:
            banner_image_file = request.files['banner_image']
            banner_image = banner_image_file.filename
            upload_to_object_storage(banner_image_file, banner_image)

        # Creating the company profile entry
        profile = CompanyProfile(
            user_id=current_user.id,
            company_name=form.company_name.data,
            description=form.description.data,
            profile_image=profile_image,
            banner_image=banner_image,
            location=form.location.data,
            email=form.email.data,
            website=form.website.data,
            social_links=form.social_links.data  # Ensure it's in a compatible format for JSON
        )

        db.session.add(profile)
        db.session.commit()
        flash("Company profile created!", "success")
        return redirect(url_for('profiles.view_company_profile', company_name=profile.slug))

    return render_template('profiles/create_company_profile.html', form=form)




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
