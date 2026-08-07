from functools import wraps
import time

from flask import request, current_app
from flask_login import current_user
from sqlalchemy.exc import (
    DBAPIError,
    DisconnectionError,
    OperationalError,
    PendingRollbackError,
)

from app import db
from app.models import ProfileView, DiscussionView, Discussion, IndividualProfile, CompanyProfile
from app.analytics.events import record_event
from app.db_retry import discard_db_session
from app.lib.db_transient_errors import (
    is_transient_db_connectivity_error,
    should_invalidate_db_connection,
)
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


def _record_discussion_view(discussion_id, *, max_attempts=2, backoff_s=0.15):
    """Best-effort discussion_view write with one retry on Neon/PgBouncer SSL blips.

    Never raises: view tracking must not break the page. Transient connectivity
    failures are retried once after invalidating the poisoned pooled socket;
    remaining failures log at WARNING with a prefix Sentry already drops.
    """
    last_exc = None
    for attempt in range(1, max_attempts + 1):
        try:
            discussion = db.session.get(Discussion, discussion_id)
            if not discussion:
                return
            discussion_view = DiscussionView(
                discussion_id=discussion_id,
                viewer_id=current_user.id if current_user.is_authenticated else None,
                ip_address=request.remote_addr,
            )
            db.session.add(discussion_view)
            db.session.commit()
            record_event(
                'discussion_viewed',
                user_id=current_user.id if current_user.is_authenticated else None,
                discussion_id=discussion.id,
                programme_id=discussion.programme_id,
                country=discussion.country,
                source='web',
            )
            return
        except PendingRollbackError as exc:
            last_exc = exc
            discard_db_session(invalidate_connection=True)
            if attempt < max_attempts:
                current_app.logger.warning(
                    "Transient DB error in track_discussion_view "
                    "(attempt %d/%d) for discussion %s: %s — retrying",
                    attempt, max_attempts, discussion_id, exc,
                )
                time.sleep(backoff_s * attempt)
                continue
        except (OperationalError, DBAPIError, DisconnectionError) as exc:
            last_exc = exc
            transient = is_transient_db_connectivity_error(exc)
            discard_db_session(
                invalidate_connection=should_invalidate_db_connection(exc),
            )
            if transient and attempt < max_attempts:
                current_app.logger.warning(
                    "Transient DB error in track_discussion_view "
                    "(attempt %d/%d) for discussion %s: %s — retrying",
                    attempt, max_attempts, discussion_id, exc,
                )
                time.sleep(backoff_s * attempt)
                continue
            if transient:
                current_app.logger.warning(
                    "Transient DB error in track_discussion_view for discussion %s: %s",
                    discussion_id, exc,
                )
            else:
                current_app.logger.error(
                    "Failed to track discussion view for discussion %s: %s",
                    discussion_id, exc,
                )
            return
        except Exception as exc:
            discard_db_session()
            current_app.logger.error(
                "Failed to track discussion view for discussion %s: %s",
                discussion_id, exc,
            )
            return

    if last_exc is not None:
        current_app.logger.warning(
            "Transient DB error in track_discussion_view for discussion %s: %s",
            discussion_id, last_exc,
        )


def track_discussion_view(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        discussion_id = kwargs.get('discussion_id')
        if discussion_id and not _viewer_is_scripted_client():
            _record_discussion_view(discussion_id)
        return f(*args, **kwargs)
    return decorated_function
