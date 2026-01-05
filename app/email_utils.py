# app/email_utils.py
import os
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Thread
from flask import current_app, url_for
from app.models import Discussion, IndividualProfile, CompanyProfile, DailyQuestionSubscriber

EMAIL_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_DELAY = 2

EMAILS_PER_SECOND = 4
BATCH_SIZE = 100
MAX_WORKERS = 4


class RateLimiter:
    """Thread-safe rate limiter for API calls"""
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


_rate_limiter = RateLimiter(EMAILS_PER_SECOND)


#This function is responsible for sending events to Loops
def send_loops_event(email_address, event_name, user_id, contact_properties, event_properties):
    api_key = os.getenv('LOOPS_API_KEY')
    url = f'https://app.loops.so/api/v1/events/{event_name}'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'email': email_address,
        'userId': user_id,
        'contactProperties': contact_properties,
        'eventProperties': event_properties
    }

    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=EMAIL_TIMEOUT)
            
            if response.status_code == 200:
                current_app.logger.info(f"Loops event '{event_name}' triggered for {email_address}.")
                return True
            else:
                current_app.logger.error(f"Failed to trigger Loops event '{event_name}' for {email_address}: {response.status_code} - {response.text}")
                return False
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                current_app.logger.warning(f"Timeout sending Loops event (attempt {attempt + 1}/{MAX_RETRIES}), retrying...")
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                current_app.logger.error(f"Timeout sending Loops event '{event_name}' for {email_address} after {MAX_RETRIES} attempts")
        except requests.exceptions.RequestException as e:
            current_app.logger.error(f"Error sending Loops event '{event_name}' for {email_address}: {e}")
            return False
    return False



#This function sends transactional emails through Loops
def send_email(recipient_email, data_variables, transactional_id, use_rate_limit=True):
    api_key = os.getenv('LOOPS_API_KEY')
    url = 'https://app.loops.so/api/v1/transactional'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'transactionalId': transactional_id,
        'email': recipient_email,
        'dataVariables': data_variables
    }

    for attempt in range(MAX_RETRIES):
        try:
            if use_rate_limit:
                _rate_limiter.acquire()
            
            response = requests.post(url, json=payload, headers=headers, timeout=EMAIL_TIMEOUT)

            if response.status_code == 200:
                return True
            elif response.status_code == 429:
                if attempt < MAX_RETRIES - 1:
                    wait_time = RETRY_DELAY * (attempt + 2)
                    time.sleep(wait_time)
                    continue
                else:
                    return False
            else:
                return False
        except requests.exceptions.Timeout:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY * (attempt + 1))
            else:
                return False
        except requests.exceptions.RequestException:
            return False
    return False




#send a password reset email
def send_password_reset_email(user, token):
    # Transactional ID for the password reset email
    transactional_id = "cm34ll2e604fmynht3l8jns9p"

    # Generate the reset URL
    reset_url = url_for('auth.password_reset', token=token, _external=True)

    # Prepare data variables
    data_variables = {
        "username": user.username or "User",  # Use username as fallback
        "resetUrl": reset_url
    }

    # Send the email with the reset link
    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



#sending a welcome email.
def send_welcome_email(user, verification_url=None):
    # Set the transactional ID for the welcome email
    transactional_id = "cm34nogvo006fxuem1vk61fjd"

    # Prepare data variables for the email
    data_variables = {
        "username": user.username or "There",
        "verificationUrl": verification_url,
        "verification_url": verification_url  # Adding both formats to ensure compatibility
    }

    # Call the send_email function with the transactional ID and data variables
    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



#account activation email. although i havent implemented this yet in registration as i thought it overkill at this stage
def send_account_activation_email(user, activation_token):
    transactional_id = "cm34oe3y003sa11ew5rw10mi6"  # ID for account activation email

    activation_url = url_for('auth.activate_account', token=activation_token, _external=True)

    # Prepare data variables for the email
    data_variables = {
        "username": user.username or "User",
        "activationUrl": activation_url
    }

    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



def get_user_discussions_summary(user):
    # Query discussions created by the user
    discussions = Discussion.query.filter_by(creator_id=user.id).all()

    # Format discussions into a single string with title and views only
    discussion_summary = "\n".join([
        f"- {discussion.title}: {discussion.views.count()} views"
        for discussion in discussions
    ])

    return discussion_summary

def send_discussion_update_email(user, summary_period="Weekly"):
    # Gather formatted discussion summary for the user
    discussion_summary = get_user_discussions_summary(user)

    # Prepare event payload
    event_properties = {
        "summaryPeriod": summary_period,
        "discussions": discussion_summary  # Pass formatted discussion summary as a single string
    }

    # Trigger the Loops event
    send_loops_event(
        email_address=user.email,
        event_name="weekly_discussion_update",
        user_id=user.id,
        contact_properties={
            "username": user.username
        },
        event_properties=event_properties
    )



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
    profile = user.individual_profile or user.company_profile

    if not profile:
        return

    missing_fields = (
        get_missing_individual_profile_fields(profile) 
        if isinstance(profile, IndividualProfile)
        else get_missing_company_profile_fields(profile)
    )

    if missing_fields:
        profile_link = url_for('settings.profile', _external=True)

        # Simplified event properties
        event_properties = {
            "profileUrl": profile_link,
            "incompleteFields": missing_fields
        }

        send_loops_event(
            email_address=user.email,
            event_name="profile_completion_reminder",
            user_id=str(user.id),  # Convert to string
            contact_properties={"name": user.username},
            event_properties=event_properties
        )


def send_discussion_notification_email(user, discussion, notification_type, additional_data=None):
    """Send real-time discussion notification email"""
    # Map notification types to transactional IDs (you'll need to create these in Loops)
    transactional_ids = {
        'new_participant': "cm34ll2e604fmynht3l8jns9p",  # Replace with actual ID when created
        'new_response': "cm34ll2e604fmynht3l8jns9p",     # Replace with actual ID when created
        'discussion_active': "cm34ll2e604fmynht3l8jns9p"  # Replace with actual ID when created
    }
    
    transactional_id = transactional_ids.get(notification_type, transactional_ids['new_participant'])
    
    # Generate discussion URL
    discussion_url = url_for('discussions.view_discussion', 
                            discussion_id=discussion.id, 
                            slug=discussion.slug, 
                            _external=True)
    
    # Prepare notification-specific data
    if notification_type == 'new_participant':
        title = f"New participant joined your discussion"
        message = f"Someone new has joined the discussion '{discussion.title}'"
    elif notification_type == 'new_response':
        title = f"New response in your discussion"
        message = f"There's new activity in your discussion '{discussion.title}'"
    else:
        title = f"Activity in your discussion"
        message = f"There's been activity in your discussion '{discussion.title}'"
    
    # Prepare data variables for email
    data_variables = {
        "username": user.username or "User",
        "discussionTitle": discussion.title,
        "discussionUrl": discussion_url,
        "notificationTitle": title,
        "notificationMessage": message,
        "discussionTopic": discussion.topic or "General"
    }
    
    # Add any additional data
    if additional_data:
        data_variables.update(additional_data)
    
    # Send the notification email
    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )


def send_weekly_discussion_digest(user):
    """Send weekly digest of discussion activity"""
    from app.models import Discussion, DiscussionParticipant, Notification
    from datetime import datetime, timedelta
    
    # Get discussions the user created in the last week
    week_ago = datetime.utcnow() - timedelta(days=7)
    
    user_discussions = Discussion.query.filter_by(creator_id=user.id)\
        .filter(Discussion.created_at >= week_ago)\
        .all()
    
    # Get activity summary for user's discussions
    discussion_summaries = []
    total_new_participants = 0
    total_new_responses = 0
    
    for discussion in user_discussions:
        # Count new participants this week
        new_participants = DiscussionParticipant.query.filter_by(discussion_id=discussion.id)\
            .filter(DiscussionParticipant.joined_at >= week_ago)\
            .count()
        
        # Count notifications (which represent activity)
        new_activity = Notification.query.filter_by(discussion_id=discussion.id)\
            .filter(Notification.created_at >= week_ago)\
            .count()
        
        if new_participants > 0 or new_activity > 0:
            discussion_url = url_for('discussions.view_discussion', 
                                   discussion_id=discussion.id, 
                                   slug=discussion.slug, 
                                   _external=True)
            
            discussion_summaries.append({
                "title": discussion.title,
                "url": discussion_url,
                "newParticipants": new_participants,
                "newActivity": new_activity,
                "topic": discussion.topic or "General"
            })
            
            total_new_participants += new_participants
            total_new_responses += new_activity
    
    # Only send digest if there's activity to report
    if discussion_summaries:
        # Transactional ID for weekly digest (create this in Loops)
        transactional_id = "cm34ll2e604fmynht3l8jns9p"  # Replace with actual ID
        
        # Prepare data variables
        data_variables = {
            "username": user.username or "User",
            "totalNewParticipants": total_new_participants,
            "totalNewResponses": total_new_responses,
            "discussionSummaries": discussion_summaries,
            "weekStart": week_ago.strftime("%B %d, %Y"),
            "weekEnd": datetime.utcnow().strftime("%B %d, %Y")
        }
        
        # Send the digest email
        send_email(
            recipient_email=user.email,
            data_variables=data_variables,
            transactional_id=transactional_id
        )
        
        return True
    
    return False  # No activity to report


def create_discussion_notification(user_id, discussion_id, notification_type, additional_data=None):
    """Create a notification and optionally send email"""
    from app.models import Notification, User, Discussion
    from app import db
    from flask import current_app
    
    try:
        # Normalize notification type to handle different formats
        if notification_type:
            notification_type = notification_type.strip().lower().replace('-', '_')
        
        # Validate notification type
        valid_types = {'new_participant', 'new_response', 'discussion_active'}
        if notification_type not in valid_types:
            current_app.logger.warning(f"Unknown notification type: {notification_type}")
            return None
        
        user = User.query.get(user_id)
        discussion = Discussion.query.get(discussion_id)
        
        if not user or not discussion:
            current_app.logger.warning(f"User {user_id} or discussion {discussion_id} not found")
            return None
        
        # Check user's notification preferences
        send_email_notification = (
            user.email_notifications and
            ((notification_type == 'new_participant' and user.discussion_participant_notifications) or
             (notification_type == 'new_response' and user.discussion_response_notifications))
        )
        
        # Generate notification content
        if notification_type == 'new_participant':
            title = f"New participant in '{discussion.title}'"
            message = f"Someone new has joined your discussion '{discussion.title}'"
        elif notification_type == 'new_response':
            title = f"New response in '{discussion.title}'"
            message = f"There's new activity in your discussion '{discussion.title}'"
        else:
            title = f"Activity in '{discussion.title}'"
            message = f"There's been activity in your discussion '{discussion.title}'"
        
        # Create the notification
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
        
        # Send email if user preferences allow
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


def _get_base_url():
    """Get the base URL for building links, works outside request context"""
    base = os.getenv('BASE_URL', 'https://societyspeaks.io')
    return base.rstrip('/')


def send_daily_question_welcome_email(subscriber):
    """Send welcome email to new daily question subscriber"""
    transactional_id = os.getenv('LOOPS_DAILY_WELCOME_ID', 'cmjx1l3au1gku0i4ahx7xxvna')
    
    base_url = _get_base_url()
    magic_link_url = f"{base_url}/daily/m/{subscriber.magic_token}"
    daily_question_url = f"{base_url}/daily"
    
    data_variables = {
        "magicLinkUrl": magic_link_url,
        "dailyQuestionUrl": daily_question_url
    }
    
    send_email(
        recipient_email=subscriber.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )


def send_daily_question_email(subscriber, question):
    """Send daily question email to subscriber with magic link"""
    from app.models import DailyQuestion
    from datetime import datetime
    
    transactional_id = os.getenv('LOOPS_DAILY_QUESTION_ID')
    if not transactional_id:
        current_app.logger.error("LOOPS_DAILY_QUESTION_ID not set - cannot send daily question email")
        return
    
    subscriber.generate_magic_token()
    from app import db
    db.session.commit()
    
    base_url = _get_base_url()
    magic_link_url = f"{base_url}/daily/m/{subscriber.magic_token}"
    question_url = f"{base_url}/daily/{question.question_date.isoformat()}"
    
    streak_message = " "
    if subscriber.current_streak > 1:
        streak_message = f"You've participated {subscriber.current_streak} days in a row!"
    
    why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."
    
    data_variables = {
        "questionNumber": str(question.question_number),
        "questionText": question.question_text,
        "questionContext": question.context or " ",
        "whyThisQuestion": why_this,
        "topicCategory": question.topic_category or "Civic",
        "magicLinkUrl": magic_link_url,
        "questionUrl": question_url,
        "streakMessage": streak_message
    }
    
    send_email(
        recipient_email=subscriber.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )
    
    subscriber.last_email_sent = datetime.utcnow()
    db.session.commit()


def _prepare_email_payload(subscriber, question):
    """Prepare email payload for a subscriber (can be called from thread)"""
    from datetime import datetime
    
    subscriber.generate_magic_token()
    
    base_url = _get_base_url()
    magic_link_url = f"{base_url}/daily/m/{subscriber.magic_token}"
    question_url = f"{base_url}/daily/{question.question_date.isoformat()}"
    
    streak_message = " "
    if subscriber.current_streak > 1:
        streak_message = f"You've participated {subscriber.current_streak} days in a row!"
    
    why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."
    
    transactional_id = os.getenv('LOOPS_DAILY_QUESTION_ID')
    
    data_variables = {
        "questionNumber": str(question.question_number),
        "questionText": question.question_text,
        "questionContext": question.context or " ",
        "whyThisQuestion": why_this,
        "topicCategory": question.topic_category or "Civic",
        "magicLinkUrl": magic_link_url,
        "questionUrl": question_url,
        "streakMessage": streak_message
    }
    
    return {
        'email': subscriber.email,
        'subscriber_id': subscriber.id,
        'data_variables': data_variables,
        'transactional_id': transactional_id,
        'magic_token': subscriber.magic_token
    }


def _send_single_email_worker(payload):
    """Worker function for sending a single email (thread-safe)"""
    try:
        success = send_email(
            recipient_email=payload['email'],
            data_variables=payload['data_variables'],
            transactional_id=payload['transactional_id'],
            use_rate_limit=True
        )
        return {'email': payload['email'], 'subscriber_id': payload['subscriber_id'], 
                'success': success, 'magic_token': payload['magic_token']}
    except Exception as e:
        return {'email': payload['email'], 'subscriber_id': payload['subscriber_id'], 
                'success': False, 'error': str(e)}


def send_daily_question_to_all_subscribers():
    """
    Send today's daily question to all active subscribers.
    Uses rate limiting and batched processing for high-volume sending (10k-20k emails).
    At 4 req/sec: 10k emails = ~42 min, 20k emails = ~84 min
    """
    from app.models import DailyQuestion, DailyQuestionSubscriber
    from app import db
    from datetime import datetime
    
    question = DailyQuestion.get_today()
    if not question:
        current_app.logger.info("No daily question to send - none published for today")
        return 0
    
    transactional_id = os.getenv('LOOPS_DAILY_QUESTION_ID')
    if not transactional_id:
        current_app.logger.error("LOOPS_DAILY_QUESTION_ID not set - cannot send daily question email")
        return 0
    
    subscribers = DailyQuestionSubscriber.query.filter_by(is_active=True).all()
    total_subscribers = len(subscribers)
    
    if total_subscribers == 0:
        current_app.logger.info("No active subscribers to send daily question to")
        return 0
    
    estimated_time = total_subscribers / EMAILS_PER_SECOND / 60
    current_app.logger.info(
        f"Starting daily question #{question.question_number} send to {total_subscribers} subscribers "
        f"(estimated time: {estimated_time:.1f} minutes at {EMAILS_PER_SECOND} emails/sec)"
    )
    
    start_time = time.time()
    sent_count = 0
    failed_count = 0
    failed_emails = []
    
    payloads = []
    for subscriber in subscribers:
        try:
            payload = _prepare_email_payload(subscriber, question)
            payloads.append(payload)
        except Exception as e:
            failed_count += 1
            current_app.logger.error(f"Error preparing email for {subscriber.email}: {e}")
    
    db.session.commit()
    
    for i in range(0, len(payloads), BATCH_SIZE):
        batch = payloads[i:i + BATCH_SIZE]
        batch_num = (i // BATCH_SIZE) + 1
        total_batches = (len(payloads) + BATCH_SIZE - 1) // BATCH_SIZE
        
        for payload in batch:
            result = _send_single_email_worker(payload)
            if result['success']:
                sent_count += 1
                try:
                    sub = DailyQuestionSubscriber.query.get(result['subscriber_id'])
                    if sub:
                        sub.last_email_sent = datetime.utcnow()
                        sub.magic_token = result.get('magic_token')
                except Exception:
                    pass
            else:
                failed_count += 1
                failed_emails.append(result['email'])
        
        db.session.commit()
        
        elapsed = time.time() - start_time
        rate = sent_count / elapsed if elapsed > 0 else 0
        current_app.logger.info(
            f"Batch {batch_num}/{total_batches} complete: {sent_count} sent, {failed_count} failed "
            f"({rate:.1f} emails/sec)"
        )
    
    elapsed_total = time.time() - start_time
    current_app.logger.info(
        f"Daily question #{question.question_number} complete: "
        f"{sent_count} sent, {failed_count} failed of {total_subscribers} "
        f"in {elapsed_total/60:.1f} minutes ({sent_count/elapsed_total:.1f} emails/sec)"
    )
    
    if failed_emails and len(failed_emails) <= 20:
        current_app.logger.warning(f"Failed emails: {', '.join(failed_emails)}")
    elif failed_emails:
        current_app.logger.warning(f"First 20 failed emails: {', '.join(failed_emails[:20])}")
    
    return sent_count


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


from datetime import datetime