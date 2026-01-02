from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app, session
from werkzeug.security import generate_password_hash, check_password_hash
from app import db, cache
from app.models import User, Discussion, IndividualProfile, CompanyProfile, ProfileView, DiscussionView, StatementVote
from flask_login import login_user, login_required, logout_user, current_user
from sqlalchemy import func
from datetime import datetime, timedelta
from app.utils import get_recent_activity
from itsdangerous import URLSafeTimedSerializer
from app.email_utils import send_password_reset_email, send_welcome_email, send_profile_completion_reminder_email, get_missing_individual_profile_fields,get_missing_company_profile_fields


auth_bp = Blueprint('auth', __name__)


from app import limiter

@auth_bp.route('/verify-email/<token>', methods=['GET'])
def verify_email(token):
    user = User.verify_reset_token(token)
    if user:
        user.email_verified = True
        db.session.commit()
        flash('Your email has been verified! You can now log in.', 'success')
    else:
        flash('That is an invalid or expired token', 'warning')
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
@limiter.limit("5/hour")
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')
        
        # Get spam patterns from config
        spam_patterns = current_app.config.get('SPAM_PATTERNS', [])
        
        # Check for spam in a case-insensitive way
        input_text = f"{username.lower()} {email.lower()}"
        if any(pattern in input_text for pattern in spam_patterns):
            flash("Registration denied due to suspicious content", "error")
            return redirect(url_for('auth.register'))

        # Validation checks
        if not username or not email or not password:
            flash("All fields are required.", "error")
            return redirect(url_for('auth.register'))

        if len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return redirect(url_for('auth.register'))

        if User.query.filter_by(email=email).first():
            flash("Email already registered. Please log in.", "error")
            return redirect(url_for('auth.register'))

        # Verify CAPTCHA
        verification = request.form.get('verification')
        expected = request.form.get('expected')
        
        # Check if values exist and are numeric before converting
        if not verification or not expected:
            flash("Incorrect verification answer. Please try again.", "error")
            return redirect(url_for('auth.register'))
        
        try:
            verification_int = int(verification)
            expected_int = int(expected)
        except (ValueError, TypeError):
            flash("Incorrect verification answer. Please try again.", "error")
            return redirect(url_for('auth.register'))
        
        if verification_int != expected_int:
            flash("Incorrect verification answer. Please try again.", "error")
            return redirect(url_for('auth.register'))

        # Hash the password and create the user
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        new_user.email_verified = False
        db.session.add(new_user)
        db.session.commit()

        # Generate verification token
        token = new_user.get_reset_token()

        # Send welcome/verification email using existing welcome email function
        verification_url = url_for('auth.verify_email', token=token, _external=True)
        send_welcome_email(new_user, verification_url=verification_url)

        flash("Please check your email to verify your account before logging in.", "info")
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')






# User login: New Users without a profile are sent to select_profile_type to create their profile. Returning Users with a profile are redirected to the dashboard.
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        # Check for invalid email or password
        if not user or not check_password_hash(user.password, password):
            flash("Invalid email or password.", "error")
            return redirect(url_for('auth.login'))

        # Log the user in
        login_user(user)
        
        # Merge any anonymous votes from this session to the user's account
        fingerprint = session.get('statement_vote_fingerprint')
        if fingerprint:
            merged = StatementVote.merge_anonymous_votes(fingerprint, user.id)
            if merged > 0:
                current_app.logger.info(f"Merged {merged} anonymous votes for user {user.id}")
        
        flash("Logged in successfully!", "success")

        # Check if the user has an individual or company profile
        profile = user.individual_profile or user.company_profile

        if not profile:
            # Redirect to profile setup if no profile exists
            return redirect(url_for('profiles.select_profile_type'))

        # If the user has a profile, check for missing fields and send reminder if necessary
        missing_fields = (
            get_missing_individual_profile_fields(profile)
            if isinstance(profile, IndividualProfile)
            else get_missing_company_profile_fields(profile)
        )

        if missing_fields:
            send_profile_completion_reminder_email(user)

        # Redirect to the dashboard if the user has a complete or partially complete profile
        return redirect(url_for('auth.dashboard'))

    return render_template('auth/login.html')





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
        profile_views = ProfileView.query.filter(
            (ProfileView.individual_profile_id == profile.id) | 
            (ProfileView.company_profile_id == profile.id)
        ).count()

    # Get recent discussions
    discussions = Discussion.query.filter_by(creator_id=current_user.id)\
        .order_by(Discussion.created_at.desc())\
        .all()

    # Get discussion views for recent discussions
    discussion_views = 0
    if discussions:
        discussion_ids = [d.id for d in discussions]
        discussion_views = DiscussionView.query.filter(
            DiscussionView.discussion_id.in_(discussion_ids)
        ).count()

    return render_template(
        'auth/dashboard.html',
        profile=profile,
        discussions=discussions,
        total_discussions=total_discussions,
        profile_views=profile_views,
        discussion_views=discussion_views
    )




@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
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
        if not new_password or len(new_password) < 6:
            flash("Password must be at least 6 characters long.", "error")
            return render_template('auth/password_reset.html', token=token)

        # Set the new password
        user.set_password(new_password)

        try:
            db.session.commit()  # Save changes to the database
            flash("Your password has been reset successfully!", "success")
            return redirect(url_for('auth.login'))
        except Exception as e:
            db.session.rollback()  # Rollback if commit fails
            flash("An error occurred while resetting your password. Please try again.", "danger")
            current_app.logger.error(f"Password reset error: {str(e)}")

    return render_template('auth/password_reset.html', token=token)