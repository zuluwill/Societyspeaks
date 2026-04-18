from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import urlparse
from app import db, cache
from app.models import User, Discussion, DiscussionFollow, DiscussionParticipant, IndividualProfile, CompanyProfile, Notification, ProfileView, DiscussionView, Response, Statement, StatementVote, OrganizationMember, Programme, DailyBriefSubscriber, DailyQuestionSubscriber
from flask_login import login_user, login_required, logout_user, current_user
from sqlalchemy import func, or_
from datetime import datetime, timedelta
from app.storage_utils import get_recent_activity
from itsdangerous import URLSafeTimedSerializer
from app.analytics.events import record_event
# Email functions (migrated from Loops to Resend)
from app.resend_client import send_password_reset_email, send_welcome_email, send_verification_email
from app.email_utils import extract_clean_email, get_missing_individual_profile_fields, get_missing_company_profile_fields
from app.lib.auth_utils import normalize_email
from app.lib.url_utils import safe_next_url
# Billing service for invitation handling
from app.billing.service import accept_invitation, get_active_subscription
from app.brief.subscription import process_subscription as process_brief_subscription
from app.brief.constants import VALID_SEND_HOURS as BRIEF_VALID_SEND_HOURS
from app.daily.utils import (
    daily_question_email_send_window_utc_label,
    monthly_digest_schedule_short,
    process_daily_question_subscription,
)
from app.programmes.access import programme_access_labels, query_accessible_programmes, ranked_programme_access_subquery
from app.programmes.permissions import can_view_programme
from app.discussions.query_utils import apply_discussion_visibility
try:
    import posthog
except ImportError:
    posthog = None
from app.lib.posthog_utils import safe_posthog_capture
from app.lib.partner_portal_session import (
    sync_partner_portal_session_for_email,
    attempt_partner_only_login,
    get_partner_login_lockout,
)


auth_bp = Blueprint('auth', __name__)


def _track_posthog(event, user_id, properties=None, flush=False, identify_properties=None):
    """Fire a PostHog event silently — never raises."""
    if not user_id:
        return
    safe_posthog_capture(
        posthog_client=posthog,
        distinct_id=str(user_id),
        event=event,
        properties=properties or {},
        flush=flush,
        identify_properties=identify_properties,
    )


from app import limiter


def _safe_referrer_or(fallback_endpoint):
    """Return same-origin referrer URL, otherwise fallback endpoint URL."""
    referrer = request.referrer
    if referrer:
        parsed = urlparse(referrer)
        if parsed.scheme in ('http', 'https') and parsed.netloc == request.host:
            return referrer
    return url_for(fallback_endpoint)


def _current_next_url():
    return safe_next_url(request.form.get('next') or request.args.get('next'))


def _set_pending_post_auth_redirect(next_url):
    safe_next = safe_next_url(next_url)
    if safe_next:
        session['pending_post_auth_redirect'] = safe_next
    else:
        session.pop('pending_post_auth_redirect', None)
    return safe_next


def _peek_pending_post_auth_redirect():
    return safe_next_url(session.get('pending_post_auth_redirect'))


def _pop_pending_post_auth_redirect():
    return safe_next_url(session.pop('pending_post_auth_redirect', None))


def _consume_pending_discussion_follow(user):
    discussion_id = session.pop('pending_follow_discussion_id', None)
    if not discussion_id or not user or not getattr(user, 'id', None):
        return None

    discussion = Discussion.query.options(
        db.joinedload(Discussion.programme)
    ).filter_by(id=discussion_id).first()
    if not discussion or discussion.partner_env == 'test':
        return None
    if discussion.programme and not can_view_programme(discussion.programme, user):
        return None

    existing_follow = DiscussionFollow.query.filter_by(
        user_id=user.id,
        discussion_id=discussion.id,
    ).first()
    if existing_follow:
        return discussion

    db.session.add(DiscussionFollow(user_id=user.id, discussion_id=discussion.id))
    try:
        db.session.commit()
        flash('Discussion saved. We will keep it handy in your dashboard.', 'success')
        return discussion
    except Exception:
        db.session.rollback()
        current_app.logger.warning(
            'Failed to save pending followed discussion %s for user %s',
            discussion_id,
            user.id,
        )
        return None


def _query_saved_discussions(user):
    query = Discussion.query.join(
        DiscussionFollow,
        DiscussionFollow.discussion_id == Discussion.id,
    ).filter(
        DiscussionFollow.user_id == user.id,
        Discussion.partner_env != 'test',
    )
    query = apply_discussion_visibility(query, user)
    return query


def _recent_participating_discussions(user, limit=6):
    activity_by_discussion = {}

    def add_activity(discussion, timestamp, activity_key):
        if not discussion or discussion.partner_env == 'test':
            return
        if discussion.programme and not can_view_programme(discussion.programme, user):
            return
        row = activity_by_discussion.setdefault(
            discussion.id,
            {
                'discussion': discussion,
                'last_activity': timestamp,
                'activity_types': set(),
            },
        )
        if timestamp and (row['last_activity'] is None or timestamp > row['last_activity']):
            row['last_activity'] = timestamp
        row['activity_types'].add(activity_key)

    participant_rows = DiscussionParticipant.query.options(
        db.joinedload(DiscussionParticipant.discussion).joinedload(Discussion.programme)
    ).filter_by(
        user_id=user.id,
    ).order_by(
        DiscussionParticipant.last_activity.desc(),
        DiscussionParticipant.id.desc(),
    ).limit(limit * 4).all()
    for participant in participant_rows:
        add_activity(
            participant.discussion,
            participant.last_activity or participant.joined_at,
            'voted',
        )

    statement_rows = Statement.query.options(
        db.joinedload(Statement.discussion).joinedload(Discussion.programme)
    ).filter(
        Statement.user_id == user.id,
        Statement.is_deleted.is_(False),
    ).order_by(
        Statement.created_at.desc(),
        Statement.id.desc(),
    ).limit(limit * 4).all()
    for statement in statement_rows:
        add_activity(statement.discussion, statement.updated_at or statement.created_at, 'statement')

    response_rows = Response.query.options(
        db.joinedload(Response.statement).joinedload(Statement.discussion).joinedload(Discussion.programme)
    ).filter(
        Response.user_id == user.id,
        Response.is_deleted.is_(False),
    ).order_by(
        Response.created_at.desc(),
        Response.id.desc(),
    ).limit(limit * 4).all()
    for response in response_rows:
        discussion = response.statement.discussion if response.statement else None
        add_activity(discussion, response.updated_at or response.created_at, 'response')

    rows = sorted(
        activity_by_discussion.values(),
        key=lambda row: row['last_activity'] or datetime.min,
        reverse=True,
    )
    return rows[:limit]


def _recent_user_contributions(user, limit=12):
    entries = []

    statement_rows = Statement.query.options(
        db.joinedload(Statement.discussion)
    ).filter(
        Statement.user_id == user.id,
        Statement.is_deleted.is_(False),
    ).order_by(
        Statement.created_at.desc(),
        Statement.id.desc(),
    ).limit(limit).all()
    for statement in statement_rows:
        discussion = statement.discussion
        if not discussion or discussion.partner_env == 'test':
            continue
        if discussion.programme and not can_view_programme(discussion.programme, user):
            continue
        entries.append(
            {
                'kind': 'statement',
                'created_at': statement.created_at,
                'title': statement.content,
                'discussion': discussion,
                'url': url_for('statements.view_statement', statement_id=statement.id),
            }
        )

    response_rows = Response.query.options(
        db.joinedload(Response.statement).joinedload(Statement.discussion)
    ).filter(
        Response.user_id == user.id,
        Response.is_deleted.is_(False),
    ).order_by(
        Response.created_at.desc(),
        Response.id.desc(),
    ).limit(limit).all()
    for response in response_rows:
        statement = response.statement
        discussion = statement.discussion if statement else None
        if not discussion or discussion.partner_env == 'test':
            continue
        if discussion.programme and not can_view_programme(discussion.programme, user):
            continue
        entries.append(
            {
                'kind': 'response',
                'created_at': response.created_at,
                'title': response.content,
                'discussion': discussion,
                'url': url_for('statements.view_response', response_id=response.id),
            }
        )

    entries.sort(key=lambda row: row['created_at'] or datetime.min, reverse=True)
    return entries[:limit]

@auth_bp.route('/verify-email/<token>', methods=['GET'])
@limiter.limit("20/minute")
def verify_email(token):
    user, expired = User.verify_email_verification_token(token)
    if user and not expired:
        if not user.email_verified:
            user.email_verified = True
            db.session.commit()
            _track_posthog('email_verified', user.id, {'user_id': user.id}, flush=True)
        flash('Your email has been verified! You can now log in.', 'success')
        return redirect(url_for('auth.login'))
    return render_template(
        'auth/verify_email_expired.html',
        expired=expired,
        email=user.email if user else None
    )


@auth_bp.route('/resend-verification', methods=['POST'])
@limiter.limit("3/hour")
def resend_verification():
    """
    POST only:
    - Authenticated users: resend to the current account and return in-context.
    - Unauthenticated users: resend to the submitted address and redirect to login.
    """
    # Authenticated requests always act on the current account — ignore any posted email
    # to prevent triggering resends for other users' addresses.
    if current_user.is_authenticated:
        user = current_user
    else:
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first() if email else None

    if user and not user.email_verified:
        try:
            token = user.get_email_verification_token()
            verification_url = url_for('auth.verify_email', token=token, _external=True)
            send_verification_email(user, verification_url)
            current_app.logger.info(f"Verification email resent to {user.email}")
        except Exception as e:
            current_app.logger.error(f"Failed to resend verification email: {e}")

    flash('If that address is registered and unverified, a new verification link has been sent.', 'info')
    if current_user.is_authenticated:
        return redirect(_safe_referrer_or('auth.dashboard'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/invite/<token>', methods=['GET'])
def handle_invitation(token):
    """Handle organization invitation links.

    If user is logged in, accept the invitation immediately.
    If not logged in, store token in session and redirect to login/register.
    """
    # Verify the invitation token is valid first
    membership = OrganizationMember.query.filter_by(
        invite_token=token,
        status='pending'
    ).first()

    if not membership:
        flash('This invitation link is invalid or has expired.', 'error')
        return redirect(url_for('auth.login'))

    org_name = membership.org.company_name if membership.org else 'an organization'

    if current_user.is_authenticated:
        # User is logged in - try to accept immediately
        try:
            accept_invitation(token, current_user)
            flash(f'Welcome to {org_name}! You now have access to the team\'s briefings.', 'success')
            return redirect(url_for('briefing.list_briefings'))
        except ValueError as e:
            flash(str(e), 'error')
            return redirect(url_for('briefing.list_briefings'))
    else:
        # Store invitation token in session for after login/register
        session['pending_invitation_token'] = token
        session['pending_invitation_org'] = org_name
        session['pending_invitation_email'] = membership.invite_email

        flash(f'You\'ve been invited to join {org_name}. Please log in or create an account to accept.', 'info')

        # If the invited email exists, send to login; otherwise register
        existing_user = User.query.filter_by(email=membership.invite_email).first() if membership.invite_email else None
        if existing_user:
            return redirect(url_for('auth.login'))
        else:
            return redirect(url_for('auth.register'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5/hour")
def register():
    import random
    next_url = _current_next_url()

    # Capture checkout intent from query params (for briefing signups)
    checkout_plan = request.args.get('checkout_plan')
    checkout_interval = request.args.get('checkout_interval', 'month')

    if checkout_plan:
        session['pending_checkout_plan'] = checkout_plan
        session['pending_checkout_interval'] = checkout_interval

    # If a logged-in user clicks "Start free trial", skip registration and go straight to Stripe
    if current_user.is_authenticated and checkout_plan:
        return redirect(url_for('billing.pending_checkout',
                                plan=checkout_plan,
                                interval=checkout_interval))

    # Get invitation context from session (set by /invite/<token> route)
    pending_invitation_email = session.get('pending_invitation_email')
    pending_invitation_org = session.get('pending_invitation_org')

    # Generate CAPTCHA numbers for GET requests or failed POST attempts
    def generate_captcha():
        num1 = random.randint(1, 9)
        num2 = random.randint(1, 9)
        session['captcha_expected'] = num1 + num2
        return num1, num2

    if request.method == 'POST':
        username = (request.form.get('username') or '').strip()
        email_raw = (request.form.get('email') or '').strip()
        password = request.form.get('password') or ''
        
        # Validation checks
        if not username or not email_raw or not password:
            flash("All fields are required.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        if len(password) < 8:
            flash("Password must be at least 8 characters.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        clean_email = extract_clean_email(email_raw)
        if clean_email is None:
            flash("Please provide a valid email address.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))
        email = clean_email.lower()

        # Get spam patterns from config
        spam_patterns = current_app.config.get('SPAM_PATTERNS', [])

        # Check for spam in a case-insensitive way
        input_text = f"{username.lower()} {email}"
        if any(pattern in input_text for pattern in spam_patterns):
            flash("Registration denied due to suspicious content", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please log in.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        # Verify CAPTCHA (server-side session validation)
        verification = request.form.get('verification')
        expected = session.pop('captcha_expected', None)  # Pop to prevent reuse

        # Check if session has expected value (prevents replay attacks)
        if expected is None:
            flash("Session expired. Please try again.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        # Check if verification answer was provided
        if not verification:
            flash("Please answer the verification question.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        try:
            verification_int = int(verification)
        except (ValueError, TypeError):
            flash("Incorrect verification answer. Please try again.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        if verification_int != expected:
            flash("Incorrect verification answer. Please try again.", "error")
            return redirect(url_for('auth.register', next=next_url) if next_url else url_for('auth.register'))

        # Hash the password and create the user
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        new_user.email_verified = False
        db.session.add(new_user)
        db.session.commit()
        record_event(
            'account_created',
            user_id=new_user.id,
            source='web',
            event_metadata={'username': username}
        )
        
        # Track user signup with PostHog
        _track_posthog('user_signed_up', new_user.id, {'username': username}, flush=True)

        # Generate email verification token (24-hour expiry, separate salt from password reset)
        token = new_user.get_email_verification_token()

        # Send welcome email with the verification link embedded
        verification_url = url_for('auth.verify_email', token=token, _external=True)
        send_welcome_email(new_user, verification_url=verification_url)

        # Auto-login the new user for frictionless checkout flow
        login_user(new_user)
        sync_partner_portal_session_for_email(new_user.email)
        _set_pending_post_auth_redirect(next_url)
        _consume_pending_discussion_follow(new_user)

        # Auto-link any pending steward invites sent to this email address
        from app.models import ProgrammeSteward
        from app.lib.time import utcnow_naive as _utcnow
        _pending_stewards = ProgrammeSteward.query.filter_by(
            pending_email=new_user.email.lower(),
            status='pending',
        ).all()
        if _pending_stewards:
            for _ps in _pending_stewards:
                _ps.user_id = new_user.id
                _ps.pending_email = None
                _ps.status = 'active'
                _ps.accepted_at = _utcnow()
                _ps.invite_token = None
            try:
                db.session.commit()
            except Exception:
                db.session.rollback()
                current_app.logger.warning('Failed to auto-link pending steward invites on registration')
        # Consume any pending steward invite token so it is not re-processed on login
        session.pop('pending_steward_invite_token', None)

        # Check for pending checkout (user came from pricing page)
        pending_plan = session.pop('pending_checkout_plan', None)
        pending_interval = session.pop('pending_checkout_interval', 'month')

        if pending_plan:
            # Direct to checkout - don't make them log in separately
            flash("Welcome! Complete your subscription setup below. We've sent a verification email to confirm your address.", "success")
            return redirect(url_for('billing.pending_checkout',
                                    plan=pending_plan,
                                    interval=pending_interval))

        # No pending checkout - normal registration flow
        flash("Welcome! We've sent a verification email. You can continue setting up your account.", "success")
        pending_redirect = _peek_pending_post_auth_redirect()
        if pending_redirect:
            return redirect(url_for('profiles.select_profile_type', next=pending_redirect))
        return redirect(url_for('profiles.select_profile_type'))

    # GET request - generate fresh CAPTCHA
    captcha_num1, captcha_num2 = generate_captcha()

    return render_template('auth/register.html',
                         invitation_email=pending_invitation_email,
                         invitation_org=pending_invitation_org,
                         next_url=next_url,
                         captcha_num1=captcha_num1,
                         captcha_num2=captcha_num2)






# User login: New Users without a profile are sent to select_profile_type to create their profile. Returning Users with a profile are redirected to the dashboard.
@auth_bp.route('/login', methods=['GET', 'POST'])
@limiter.limit("10/minute")
def login():
    next_url = _current_next_url()
    # Guard: if a concurrent/duplicate POST arrives after the first already
    # logged the user in, skip re-processing to prevent duplicate flash messages.
    if current_user.is_authenticated:
        profile = current_user.individual_profile or current_user.company_profile
        if not profile:
            destination = next_url or _peek_pending_post_auth_redirect()
            if destination:
                return redirect(url_for('profiles.select_profile_type', next=destination))
            return redirect(url_for('profiles.select_profile_type'))
        return redirect(next_url or _peek_pending_post_auth_redirect() or url_for('auth.dashboard'))

    if request.method == 'POST':
        email = normalize_email(request.form.get('email'))
        password = request.form.get('password', '')

        user = User.query.filter(func.lower(User.email) == email).first()

        # No User record - check whether this is a partner-only account so
        # partners who never created a main-site account can still sign in here
        # and land directly on their portal dashboard.
        if not user:
            partner_response = attempt_partner_only_login(email, password)
            if partner_response:
                return partner_response
            remaining = get_partner_login_lockout(email)
            if remaining > 0:
                flash(
                    f"Too many failed attempts. Please try again in {remaining} seconds.",
                    "error",
                )
                return redirect(url_for('auth.login', next=next_url) if next_url else url_for('auth.login'))
            flash("Invalid email or password.", "error")
            return redirect(url_for('auth.login', next=next_url) if next_url else url_for('auth.login'))

        # User record found - verify password
        if not check_password_hash(user.password, password):
            flash("Invalid email or password.", "error")
            return redirect(url_for('auth.login', next=next_url) if next_url else url_for('auth.login'))

        # Log the user in
        login_user(user)
        _set_pending_post_auth_redirect(next_url)
        _consume_pending_discussion_follow(user)

        # Keep partner portal session in sync with the authenticated user so a
        # reused browser session cannot retain access from another account.
        sync_partner_portal_session_for_email(user.email)

        # Update last login timestamp and record event
        try:
            from app.lib.time import utcnow_naive
            user.last_login_at = utcnow_naive()
            db.session.commit()
        except Exception:
            db.session.rollback()

        record_event('user_logged_in', user_id=user.id, event_metadata={'method': 'password'})

        # Track login with PostHog
        _track_posthog('user_logged_in', user.id, {'email': user.email, 'method': 'password'},
                       identify_properties={'email': user.email, 'username': user.username},
                       flush=True)
        
        # Merge any anonymous votes from this session to the user's account
        fingerprint = session.get('statement_vote_fingerprint')
        if fingerprint:
            merged = StatementVote.merge_anonymous_votes(fingerprint, user.id)
            if merged > 0:
                current_app.logger.info(f"Merged {merged} anonymous votes for user {user.id}")
        
        flash("Logged in successfully!", "success")

        # Check for pending steward invite stored before login redirect
        pending_steward_token = session.pop('pending_steward_invite_token', None)
        if pending_steward_token:
            return redirect(url_for('programmes.accept_steward_invite', token=pending_steward_token))

        # Check for pending organization invitation
        pending_invite_token = session.pop('pending_invitation_token', None)
        session.pop('pending_invitation_org', None)  # Clean up
        session.pop('pending_invitation_email', None)  # Clean up

        if pending_invite_token:
            try:
                membership = accept_invitation(pending_invite_token, user)
                org_name = membership.org.company_name if membership.org else 'the organization'
                flash(f'Welcome to {org_name}! You now have access to the team\'s briefings.', 'success')
                return redirect(url_for('briefing.list_briefings'))
            except ValueError as e:
                flash(str(e), 'warning')
                # Continue with normal login flow

        # Clean up any stale checkout session data
        # (New registrations now auto-login and redirect to checkout directly)
        session.pop('pending_checkout_plan', None)
        session.pop('pending_checkout_interval', None)

        # Check if the user has an individual or company profile
        profile = user.individual_profile or user.company_profile

        if not profile:
            # Redirect to profile setup if no profile exists
            pending_redirect = _peek_pending_post_auth_redirect()
            if pending_redirect:
                return redirect(url_for('profiles.select_profile_type', next=pending_redirect))
            return redirect(url_for('profiles.select_profile_type'))

        # If the user has a profile, check for missing fields and send reminder if necessary
        missing_fields = (
            get_missing_individual_profile_fields(profile)
            if isinstance(profile, IndividualProfile)
            else get_missing_company_profile_fields(profile)
        )

        # Send profile completion reminder if there are missing fields, at most once per 7 days
        if missing_fields:
            _reminder_cache_key = f"profile_reminder_sent:{user.id}"
            _already_sent = False
            try:
                _already_sent = bool(cache.get(_reminder_cache_key))
            except Exception:
                pass

            if not _already_sent:
                from app.resend_client import send_profile_completion_reminder_email

                if isinstance(profile, IndividualProfile):
                    profile_url = url_for('profiles.edit_individual_profile',
                                         username=profile.slug, _external=True)
                else:
                    profile_url = url_for('profiles.edit_company_profile',
                                         company_name=profile.slug, _external=True)

                try:
                    send_profile_completion_reminder_email(user, missing_fields, profile_url)
                    # Suppress further reminders for 7 days
                    cache.set(_reminder_cache_key, '1', timeout=7 * 24 * 3600)
                except Exception as e:
                    current_app.logger.error(f"Failed to send profile reminder: {e}")

        # Redirect to the dashboard if the user has a complete or partially complete profile
        return redirect(_pop_pending_post_auth_redirect() or url_for('auth.dashboard'))

    return render_template('auth/login.html', next_url=next_url)





# Renders the user's dashboard
@auth_bp.route('/dashboard')
@login_required
def dashboard():
    profile = current_user.individual_profile or current_user.company_profile

    # Calculate total discussions
    total_discussions = Discussion.query.filter_by(creator_id=current_user.id).count()

    # Calculate profile views
    profile_views = 0
    if profile:
        if current_user.profile_type == 'individual':
            profile_views = ProfileView.query.filter_by(individual_profile_id=profile.id).count()
        elif current_user.profile_type == 'company':
            profile_views = ProfileView.query.filter_by(company_profile_id=profile.id).count()

    # Discussion views across ALL user's discussions (for the stat)
    owned_discussion_ids = db.session.query(Discussion.id).filter_by(creator_id=current_user.id)
    discussion_views = db.session.query(func.count(DiscussionView.id)).filter(
        DiscussionView.discussion_id.in_(owned_discussion_ids)
    ).scalar() or 0

    # Get the 6 most recent discussions for the dashboard preview
    discussions = Discussion.query.filter_by(creator_id=current_user.id)\
        .order_by(Discussion.created_at.desc())\
        .limit(6).all()

    # Build the access subquery once, reuse it for both the count and the programme list
    ranked_access = ranked_programme_access_subquery(current_user)
    total_programmes = db.session.query(func.count()).select_from(ranked_access).scalar() or 0

    _access_labels = programme_access_labels()
    _prog_rows = db.session.query(Programme, ranked_access.c.access_rank).join(
        ranked_access, ranked_access.c.programme_id == Programme.id
    ).order_by(Programme.updated_at.desc()).limit(6).all()
    workspace_programmes = []
    for prog, rank in _prog_rows:
        access_rank = int(rank or 1)
        workspace_programmes.append(
            {
                'programme': prog,
                'access_label': _access_labels.get(access_rank, 'Invited participant'),
                'access_rank': access_rank,
                'can_manage_settings': access_rank >= 3,
            }
        )

    brief_sub = DailyBriefSubscriber.query.filter_by(email=current_user.email).first()
    dq_sub = DailyQuestionSubscriber.query.filter_by(email=current_user.email).first()
    active_subscription = get_active_subscription(current_user)
    has_briefings_plan = bool(active_subscription)
    participating_discussions = _recent_participating_discussions(current_user, limit=6)
    recent_contributions = _recent_user_contributions(current_user, limit=1)
    saved_discussions = _query_saved_discussions(current_user).order_by(
        DiscussionFollow.created_at.desc(),
        Discussion.id.desc(),
    ).limit(6).all()
    recent_notifications = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    ).limit(5).all()
    unread_notifications = Notification.unread_count_for_user(current_user.id)
    continue_item = recent_contributions[0] if recent_contributions else None
    continue_discussion = continue_item['discussion'] if continue_item else None
    continue_url = continue_item['url'] if continue_item else None
    continue_label = None
    continue_summary = None
    if continue_item:
        continue_label = 'Continue your latest response' if continue_item['kind'] == 'response' else 'Continue your latest statement'
        continue_summary = continue_item['title']
    elif participating_discussions:
        continue_discussion = participating_discussions[0]['discussion']
        continue_url = url_for(
            'discussions.view_discussion',
            discussion_id=continue_discussion.id,
            slug=continue_discussion.slug,
        )
        continue_label = 'Continue this discussion'
        continue_summary = continue_discussion.description or None

    return render_template(
        'auth/dashboard.html',
        profile=profile,
        discussions=discussions,
        total_discussions=total_discussions,
        profile_views=profile_views,
        discussion_views=discussion_views,
        workspace_programmes=workspace_programmes,
        total_programmes=total_programmes,
        brief_sub=brief_sub,
        dq_sub=dq_sub,
        has_briefings_plan=has_briefings_plan,
        active_subscription=active_subscription,
        participating_discussions=participating_discussions,
        recent_notifications=recent_notifications,
        saved_discussions=saved_discussions,
        unread_notifications=unread_notifications,
        continue_discussion=continue_discussion,
        continue_url=continue_url,
        continue_label=continue_label,
        continue_summary=continue_summary,
        dq_send_days=DailyQuestionSubscriber.SEND_DAYS,
        dq_monthly_schedule_short=monthly_digest_schedule_short(),
        dq_daily_send_window_label=daily_question_email_send_window_utc_label(),
    )


@auth_bp.route('/dashboard/subscribe', methods=['POST'])
@login_required
def dashboard_subscribe():
    """One-click subscription to daily email products from the dashboard."""
    sub_type = request.form.get('subscription_type', '')
    email = current_user.email

    if sub_type == 'brief':
        try:
            preferred_hour = int(request.form.get('preferred_hour', 18))
        except (ValueError, TypeError):
            preferred_hour = 18
        if preferred_hour not in BRIEF_VALID_SEND_HOURS:
            preferred_hour = 18
        cadence = request.form.get('cadence', 'daily')
        if cadence not in ('daily', 'weekly'):
            cadence = 'daily'
        timezone = request.form.get('timezone', 'UTC').strip() or 'UTC'
        try:
            import pytz as _pytz
            _pytz.timezone(timezone)
        except Exception:
            timezone = 'UTC'
        try:
            preferred_weekly_day = int(request.form.get('preferred_weekly_day', 6))
            if not (0 <= preferred_weekly_day <= 6):
                preferred_weekly_day = 6
        except (ValueError, TypeError):
            preferred_weekly_day = 6

        result = process_brief_subscription(
            email=email,
            timezone=timezone,
            preferred_hour=preferred_hour,
            cadence=cadence,
            preferred_weekly_day=preferred_weekly_day,
            update_preferences_on_reactivate=True,
            set_session=False,
            track_posthog=False,
            source='dashboard',
        )
        if result['status'] == 'already_active':
            flash('You\'re already subscribed to the Daily Brief!', 'info')
        elif result['status'] == 'reactivated':
            flash('Welcome back! Your Daily Brief subscription has been reactivated.', 'success')
        elif result['status'] == 'created':
            flash(f'Subscribed! Your first Daily Brief will arrive at {email}.', 'success')
        else:
            flash('Something went wrong. Please try again.', 'error')

    elif sub_type == 'daily_question':
        frequency = request.form.get('email_frequency', 'weekly')
        if frequency not in DailyQuestionSubscriber.VALID_EMAIL_FREQUENCIES:
            frequency = 'weekly'
        timezone_val = request.form.get('timezone', '').strip() or None
        send_day = request.form.get('preferred_send_day', '1')
        send_hour = request.form.get('preferred_send_hour', '9')

        result = process_daily_question_subscription(
            email,
            email_frequency=frequency,
            timezone=timezone_val,
            preferred_send_day=send_day,
            preferred_send_hour=send_hour,
            update_delivery_preferences_on_reactivate=True,
            track_posthog=False,
        )
        if result['status'] == 'already_active':
            flash('You\'re already subscribed to the Daily Question!', 'info')
        elif result['status'] == 'reactivated':
            flash('Welcome back! Your Daily Question subscription has been reactivated.', 'success')
        elif result['status'] == 'created':
            flash(f'Subscribed! Your first Daily Question will arrive at {email}.', 'success')
        else:
            flash('Something went wrong. Please try again.', 'error')

    else:
        flash('Unknown subscription type.', 'error')

    return redirect(url_for('auth.dashboard') + '#email-subscriptions')


@auth_bp.route('/dashboard/discussions')
@login_required
def my_discussions():
    page = max(request.args.get('page', 1, type=int), 1)
    q = request.args.get('q', '').strip()[:100]

    query = Discussion.query.filter_by(creator_id=current_user.id)
    if q:
        query = query.filter(Discussion.title.ilike(f'%{q}%'))

    pagination = query.order_by(Discussion.created_at.desc(), Discussion.id.desc()).paginate(
        page=page, per_page=12, error_out=False
    )
    return render_template(
        'auth/discussions.html',
        discussions=pagination.items,
        pagination=pagination,
        q=q,
    )


@auth_bp.route('/dashboard/participation')
@login_required
def participation():
    participating_discussions = _recent_participating_discussions(current_user, limit=24)
    recent_contributions = _recent_user_contributions(current_user, limit=20)
    return render_template(
        'auth/participation.html',
        participating_discussions=participating_discussions,
        recent_contributions=recent_contributions,
    )


@auth_bp.route('/dashboard/saved')
@login_required
def saved_discussions():
    page = max(request.args.get('page', 1, type=int), 1)
    q = request.args.get('q', '').strip()[:100]

    query = _query_saved_discussions(current_user)
    if q:
        query = query.filter(
            or_(
                Discussion.title.ilike(f'%{q}%'),
                Discussion.description.ilike(f'%{q}%'),
            )
        )

    pagination = query.order_by(
        DiscussionFollow.created_at.desc(),
        Discussion.id.desc(),
    ).paginate(page=page, per_page=12, error_out=False)
    return render_template(
        'auth/saved_discussions.html',
        discussions=pagination.items,
        pagination=pagination,
        q=q,
    )


@auth_bp.route('/dashboard/notifications')
@login_required
def notifications():
    page = max(request.args.get('page', 1, type=int), 1)
    pagination = Notification.query.filter_by(user_id=current_user.id).order_by(
        Notification.created_at.desc(),
        Notification.id.desc(),
    ).paginate(page=page, per_page=20, error_out=False)
    return render_template(
        'auth/notifications.html',
        notifications=pagination.items,
        pagination=pagination,
        unread_notifications=Notification.unread_count_for_user(current_user.id),
    )


@auth_bp.route('/dashboard/notifications/<int:notification_id>/read', methods=['POST'])
@login_required
def mark_notification_read(notification_id):
    notification = Notification.query.filter_by(
        id=notification_id,
        user_id=current_user.id,
    ).first_or_404()
    if not notification.is_read:
        notification.is_read = True
        db.session.commit()
    return redirect(_safe_referrer_or('auth.notifications'))


@auth_bp.route('/dashboard/notifications/read-all', methods=['POST'])
@login_required
def mark_all_notifications_read():
    updated = Notification.mark_all_as_read_for_user(current_user.id)
    if updated:
        flash('All notifications marked as read.', 'success')
    else:
        flash('You have no unread notifications.', 'info')
    return redirect(_safe_referrer_or('auth.notifications'))


@auth_bp.route('/logout')
@login_required
def logout():
    user_id = str(current_user.id)
    logout_user()
    
    # Clear all session data to prevent stale data persisting
    session.clear()
    
    # Track logout with PostHog
    _track_posthog('user_logged_out', user_id)
    
    flash("Logged out successfully.", "success")
    return redirect(url_for('main.index'))


def generate_password_reset_token(user_email):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    return serializer.dumps(user_email, salt='password-reset-salt')

def verify_password_reset_token(token, expiration=3600):
    serializer = URLSafeTimedSerializer(current_app.config['SECRET_KEY'])
    try:
        email = serializer.loads(token, salt='password-reset-salt', max_age=expiration)
    except Exception:
        return None
    return email



@auth_bp.route('/password-reset', methods=['GET', 'POST'])
def password_reset_request():
    if request.method == 'POST':
        email = request.form.get('email')
        user = User.query.filter_by(email=email).first()

        if user:
            # Generate a secure token for resetting the password
            reset_token = user.get_reset_token()

            # Send the password reset email with the generated token
            send_password_reset_email(user, reset_token)

            _track_posthog('password_reset_requested', user.id, {'user_id': user.id})

        flash("Password reset instructions have been sent to your email.", "info")
        return redirect(url_for('auth.login'))

    return render_template('auth/password_reset_request.html')



@auth_bp.route('/password-reset/<token>', methods=['GET', 'POST'])
def password_reset(token):
    # Verify the token and retrieve the user
    user = User.verify_reset_token(token)

    if not user:
        flash("The password reset link is invalid or has expired.", "danger")
        return redirect(url_for('auth.password_reset_request'))

    if request.method == 'POST':
        new_password = request.form.get('new_password')

        # Validate the new password (for example, check minimum length)
        if not new_password or len(new_password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template('auth/password_reset.html', token=token)

        # Set the new password
        user.set_password(new_password)

        try:
            db.session.commit()  # Save changes to the database
            _track_posthog('password_reset_completed', user.id, {'user_id': user.id})
            flash("Your password has been reset successfully!", "success")
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()  # Rollback if commit fails
            flash("An error occurred while resetting your password. Please try again.", "danger")
            current_app.logger.error(f"Password reset error: {str(e)}")

    return render_template('auth/password_reset.html', token=token)