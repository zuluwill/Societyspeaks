from functools import wraps
from flask import request, current_app
from flask_login import current_user
from app import db
from app.models import ProfileView, DiscussionView, Discussion, IndividualProfile, CompanyProfile

def track_profile_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = kwargs.get('username')
        company_name = kwargs.get('company_name')

        if username:
            current_app.logger.debug(f"Tracking view for individual profile: {username}")
            profile = IndividualProfile.query.filter_by(slug=username).first()
            if profile:
                current_app.logger.debug(f"Found individual profile with ID: {profile.id}")
                profile_view = ProfileView(
                    individual_profile_id=profile.id,  # Changed from profile_id
                    viewer_id=current_user.id if current_user.is_authenticated else None,
                    ip_address=request.remote_addr
                )
                db.session.add(profile_view)
                db.session.commit()
        elif company_name:
            profile = CompanyProfile.query.filter_by(slug=company_name).first()
            if profile:
                current_app.logger.debug(f"Found company profile with ID: {profile.id}")
                profile_view = ProfileView(
                    company_profile_id=profile.id,  # Changed for company profiles
                    viewer_id=current_user.id if current_user.is_authenticated else None,
                    ip_address=request.remote_addr
                )
                db.session.add(profile_view)
                db.session.commit()

        return f(*args, **kwargs)
    return decorated_function


def track_discussion_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        discussion_id = kwargs.get('discussion_id')
        if discussion_id:
            # Check if the discussion exists before tracking the view
            discussion = Discussion.query.get(discussion_id)
            if discussion:
                try:
                    # Create a new view record only if discussion exists
                    discussion_view = DiscussionView(
                        discussion_id=discussion_id,
                        viewer_id=current_user.id if current_user.is_authenticated else None,
                        ip_address=request.remote_addr
                    )
                    db.session.add(discussion_view)
                    db.session.commit()
                except Exception as e:
                    # Log the error but don't crash the application
                    current_app.logger.error(f"Failed to track discussion view for discussion {discussion_id}: {e}")
                    db.session.rollback()
        return f(*args, **kwargs)
    return decorated_function