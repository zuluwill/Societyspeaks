from flask import Blueprint, render_template, redirect, url_for, request, flash
from werkzeug.security import generate_password_hash, check_password_hash
from app import db
from app.models import User, Discussion
from flask_login import login_user, login_required, logout_user, current_user

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        email = request.form.get('email')
        password = request.form.get('password')

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

        # Hash the password and create the user
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, email=email, password=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash("Registration successful! You can now log in.", "success")
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html')


#user login: New Users without a profile are sent to select_profile_type to create their profile. Returning Users with a profile are redirected to the dashboard.
@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        user = User.query.filter_by(email=email).first()

        if not user or not check_password_hash(user.password, password):
            flash("Invalid email or password.", "error")
            return redirect(url_for('auth.login'))

        login_user(user)
        flash("Logged in successfully!", "success")

        # Redirect to dashboard, check if user has profile or redirect to profile setup
        if not (user.individual_profile or user.company_profile):
            return redirect(url_for('profiles.select_profile_type'))

        return redirect(url_for('auth.dashboard'))

    return render_template('auth/login.html')



#renders the users dashboard
@auth_bp.route('/dashboard')
@login_required
def dashboard():
    profile = current_user.individual_profile or current_user.company_profile
    discussions = Discussion.query.filter_by(creator_id=current_user.id).order_by(Discussion.created_at.desc()).limit(5).all()
    return render_template('auth/dashboard.html', profile=profile, discussions=discussions)

@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash("Logged out successfully.", "success")
    return redirect(url_for('main.index'))



# Password reset request route
@auth_bp.route('/password-reset', methods=['GET', 'POST'])
def password_reset_request():
    if request.method == 'POST':
        email = request.form.get('email')
        # Logic to send password reset email goes here
        flash("Password reset instructions have been sent to your email.", "info")
        return redirect(url_for('auth.login'))

    return render_template('auth/password_reset_request.html')  # Updated path

# Password reset route
@auth_bp.route('/password-reset/<token>', methods=['GET', 'POST'])
def password_reset(token):
    if request.method == 'POST':
        new_password = request.form.get('new_password')
        # Logic to verify token and update password goes here
        flash("Your password has been reset successfully!", "success")
        return redirect(url_for('auth.login'))

    return render_template('auth/password_reset.html')  # Updated path
