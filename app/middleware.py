from functools import wraps
from flask import request, current_app
from flask_login import current_user
from app import db
from app.models import ProfileView, DiscussionView, Discussion, IndividualProfile, CompanyProfile
from app.analytics.events import record_event
from app.lib.session_policy import SESSION_SKIP_UA_INDICATORS, user_agent_is_bot


def _viewer_is_scripted_client():
    """Skip view tracking for scripted clients (crawlers, python-requests, curl).

    View rows are written on every GET, so crawler floods dominated both
    discussion_view and analytics_event (June 2026: 556k crawler views in one
    month; 99.99% of discussion_viewed rows carried no user). Browser-UA
    crawlers still pass this check — analysis must additionally filter — but
    the scripted flood stops here.
    """
    return user_agent_is_bot(
        request.headers.get('User-Agent'), SESSION_SKIP_UA_INDICATORS
    )


def track_profile_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        username = kwargs.get('username')
        company_name = kwargs.get('company_name')

        if _viewer_is_scripted_client():
            return f(*args, **kwargs)

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
        if discussion_id and not _viewer_is_scripted_client():
            # Check if the discussion exists before tracking the view
            discussion = db.session.get(Discussion, discussion_id)
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
                    record_event(
                        'discussion_viewed',
                        user_id=current_user.id if current_user.is_authenticated else None,
                        discussion_id=discussion.id,
                        programme_id=discussion.programme_id,
                        country=discussion.country,
                        source='web'
                    )
                except Exception as e:
                    # Log the error but don't crash the application
                    current_app.logger.error(f"Failed to track discussion view for discussion {discussion_id}: {e}")
                    db.session.rollback()
        return f(*args, **kwargs)
    return decorated_function