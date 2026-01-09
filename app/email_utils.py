# app/email_utils.py
"""
Email utilities - helper functions and wrappers.
All actual email sending is done via Resend (see app/resend_client.py).

Note: RateLimiter is kept here as it's used by app/brief/email_client.py
"""
import time
import threading
from flask import current_app, url_for
from app.models import IndividualProfile, CompanyProfile


class RateLimiter:
    """Thread-safe rate limiter for API calls.
    
    Used by:
    - app/brief/email_client.py for brief email sending
    - app/resend_client.py for transactional emails
    """
    def __init__(self, rate_per_second):
        self.rate = rate_per_second
        self.min_interval = 1.0 / rate_per_second
        self.last_call = 0
        self.lock = threading.Lock()
    
    def acquire(self):
        """Wait until we can make another call"""
        with self.lock:
            now = time.time()
            time_since_last = now - self.last_call
            if time_since_last < self.min_interval:
                time.sleep(self.min_interval - time_since_last)
            self.last_call = time.time()


def get_missing_individual_profile_fields(profile):
    missing_fields = []
    if not profile.full_name:
        missing_fields.append("Full Name")
    if not profile.bio:
        missing_fields.append("Bio")
    if not profile.city:
        missing_fields.append("City")
    if not profile.country:
        missing_fields.append("Country")
    if not profile.profile_image:
        missing_fields.append("Profile Image")
    return missing_fields


def get_missing_company_profile_fields(profile):
    missing_fields = []
    if not profile.company_name:
        missing_fields.append("Company Name")
    if not profile.description:
        missing_fields.append("Description")
    if not profile.city:
        missing_fields.append("City")
    if not profile.country:
        missing_fields.append("Country")
    if not profile.logo:
        missing_fields.append("Company Logo")
    return missing_fields


def send_profile_completion_reminder_email(user):
    """Send profile completion reminder email via Resend"""
    from app.resend_client import send_profile_completion_reminder_email as resend_send_reminder
    
    if not user.email:
        return False
    
    profile = user.individual_profile or user.company_profile
    if not profile or not profile.slug:
        return False

    missing_fields = (
        get_missing_individual_profile_fields(profile) 
        if isinstance(profile, IndividualProfile)
        else get_missing_company_profile_fields(profile)
    )

    if not missing_fields:
        return False

    if isinstance(profile, IndividualProfile):
        profile_url = url_for('profiles.edit_individual_profile', 
                               username=profile.slug, _external=True)
    else:
        profile_url = url_for('profiles.edit_company_profile', 
                               company_name=profile.slug, _external=True)

    return resend_send_reminder(user, missing_fields, profile_url)


def send_discussion_notification_email(user, discussion, notification_type, additional_data=None):
    """Send real-time discussion notification email via Resend"""
    from app.resend_client import send_discussion_notification_email as resend_send_notification
    return resend_send_notification(user, discussion, notification_type, additional_data)


def create_discussion_notification(user_id, discussion_id, notification_type, additional_data=None):
    """Create a notification and optionally send email"""
    from app.models import Notification, User, Discussion
    from app import db
    
    try:
        if notification_type:
            notification_type = notification_type.strip().lower().replace('-', '_')
        
        valid_types = {'new_participant', 'new_response', 'discussion_active'}
        if notification_type not in valid_types:
            current_app.logger.warning(f"Unknown notification type: {notification_type}")
            return None
        
        user = User.query.get(user_id)
        discussion = Discussion.query.get(discussion_id)
        
        if not user or not discussion:
            current_app.logger.warning(f"User {user_id} or discussion {discussion_id} not found")
            return None
        
        send_email_notification = (
            user.email_notifications and
            ((notification_type == 'new_participant' and user.discussion_participant_notifications) or
             (notification_type == 'new_response' and user.discussion_response_notifications))
        )
        
        if notification_type == 'new_participant':
            title = f"New participant in '{discussion.title}'"
            message = f"Someone new has joined your discussion '{discussion.title}'"
        elif notification_type == 'new_response':
            title = f"New response in '{discussion.title}'"
            message = f"There's new activity in your discussion '{discussion.title}'"
        else:
            title = f"Activity in '{discussion.title}'"
            message = f"There's been activity in your discussion '{discussion.title}'"
        
        notification = Notification(
            user_id=user_id,
            discussion_id=discussion_id,
            type=notification_type,
            title=title,
            message=message,
            email_sent=False
        )
        
        db.session.add(notification)
        db.session.commit()
        
        if send_email_notification:
            try:
                send_discussion_notification_email(user, discussion, notification_type, additional_data)
                notification.email_sent = True
                db.session.commit()
            except Exception as e:
                current_app.logger.error(f"Failed to send notification email: {e}")
        
        return notification
        
    except Exception as e:
        current_app.logger.error(f"Failed to create notification: {e}")
        try:
            db.session.rollback()
        except Exception:
            pass
        return None


def bulk_subscribe_existing_users(exclude_patterns=None):
    """
    Subscribe all existing registered users to daily questions.
    Excludes test/bot accounts and users who have previously unsubscribed.
    
    Returns tuple: (subscribed_count, skipped_count, already_subscribed_count)
    """
    from app.models import User, DailyQuestionSubscriber
    from app import db
    
    if exclude_patterns is None:
        exclude_patterns = ['test', 'bot', 'fake', 'demo', 'example']
    
    users = User.query.filter(User.email.isnot(None)).all()
    
    subscribed = 0
    skipped = 0
    already_subscribed = 0
    
    for user in users:
        email_lower = user.email.lower() if user.email else ''
        username_lower = user.username.lower() if user.username else ''
        
        is_excluded = any(
            pattern in email_lower or pattern in username_lower 
            for pattern in exclude_patterns
        )
        
        if is_excluded:
            skipped += 1
            current_app.logger.debug(f"Skipping test/bot user: {user.username}")
            continue
        
        existing = DailyQuestionSubscriber.query.filter_by(email=user.email).first()
        if existing:
            if not existing.user_id:
                existing.user_id = user.id
                db.session.commit()
            already_subscribed += 1
            continue
        
        try:
            subscriber = DailyQuestionSubscriber(
                email=user.email,
                user_id=user.id,
                is_active=True
            )
            subscriber.generate_magic_token()
            db.session.add(subscriber)
            db.session.commit()
            subscribed += 1
            current_app.logger.info(f"Subscribed existing user: {user.username} ({user.email})")
        except Exception as e:
            db.session.rollback()
            current_app.logger.error(f"Error subscribing {user.email}: {e}")
            skipped += 1
    
    current_app.logger.info(
        f"Bulk subscribe complete: {subscribed} new, {already_subscribed} existing, {skipped} skipped"
    )
    return subscribed, skipped, already_subscribed
