from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from app import db
from app.models import User
from .forms import ChangePasswordForm  # Import the form

settings_bp = Blueprint('settings', __name__)

@settings_bp.route('/settings', methods=['GET', 'POST'])
@login_required
def view_settings():
    form = ChangePasswordForm()  # Initialize the form
    
    # Handle notification settings update
    if request.method == 'POST' and 'update_notifications' in request.form:
        try:
            current_user.email_notifications = 'email_notifications' in request.form
            current_user.discussion_participant_notifications = 'discussion_participant_notifications' in request.form
            current_user.discussion_response_notifications = 'discussion_response_notifications' in request.form
            current_user.weekly_digest_enabled = 'weekly_digest_enabled' in request.form
            
            db.session.commit()
            flash('Notification preferences updated successfully.', 'success')
        except Exception as e:
            db.session.rollback()
            flash('Failed to update notification preferences. Please try again.', 'danger')
        
        return redirect(url_for('settings.view_settings'))

    return render_template('settings/settings.html', form=form)

@settings_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    form = ChangePasswordForm(request.form)

    if form.validate_on_submit():
        current_password = form.current_password.data
        new_password = form.new_password.data
        confirm_password = form.confirm_password.data

        if not check_password_hash(current_user.password, current_password):
            flash('Current password is incorrect.', 'danger')
            return redirect(url_for('settings.view_settings'))

        if new_password != confirm_password:
            flash('New passwords do not match.', 'danger')
            return redirect(url_for('settings.view_settings'))

        # Update user's password
        current_user.password = generate_password_hash(new_password)
        db.session.commit()
        flash('Password updated successfully.', 'success')
        return redirect(url_for('settings.view_settings'))

    flash('Please correct the errors in the form.', 'danger')
    return redirect(url_for('settings.view_settings'))


@settings_bp.route('/delete-account', methods=['POST'])
@login_required
def delete_account():
    user = User.query.get(current_user.id)
    if user:
        # Remove user account and related data
        db.session.delete(user)
        db.session.commit()
        flash('Your account has been deleted successfully.', 'success')
        return redirect(url_for('auth.logout'))
    flash('Account deletion failed. Please try again.', 'error')
    return redirect(url_for('settings.view_settings'))