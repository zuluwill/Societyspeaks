from flask_wtf import FlaskForm
from wtforms import PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField('Current Password', validators=[DataRequired()])
    new_password = PasswordField('New Password', validators=[DataRequired(), Length(min=8, message='Password must be at least 8 characters.')])
    confirm_password = PasswordField('Confirm New Password', validators=[DataRequired(), EqualTo('new_password', message="Passwords must match.")])
    submit = SubmitField('Update Password')


class NotificationPreferencesForm(FlaskForm):
    email_notifications = BooleanField('Enable email notifications')
    discussion_participant_notifications = BooleanField('New participants')
    discussion_response_notifications = BooleanField('Discussion activity')
    discussion_update_notifications = BooleanField('Discussion updates')
    weekly_digest_enabled = BooleanField('Weekly digest')
    submit = SubmitField('Save Notification Preferences')


class DeleteAccountForm(FlaskForm):
    submit = SubmitField('Delete Account')
