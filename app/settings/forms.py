from flask_wtf import FlaskForm
from wtforms import PasswordField, SubmitField, BooleanField
from wtforms.validators import DataRequired, Length, EqualTo
from flask_babel import lazy_gettext as _l


class ChangePasswordForm(FlaskForm):
    current_password = PasswordField(_l('Current Password'), validators=[DataRequired()])
    new_password = PasswordField(_l('New Password'), validators=[DataRequired(), Length(min=8, message=_l('Password must be at least 8 characters.'))])
    confirm_password = PasswordField(_l('Confirm New Password'), validators=[DataRequired(), EqualTo('new_password', message=_l("Passwords must match."))])
    submit = SubmitField(_l('Update Password'))


class NotificationPreferencesForm(FlaskForm):
    email_notifications = BooleanField(_l('Enable email notifications'))
    discussion_participant_notifications = BooleanField(_l('New participants'))
    discussion_response_notifications = BooleanField(_l('Discussion activity'))
    discussion_update_notifications = BooleanField(_l('Discussion updates'))
    weekly_digest_enabled = BooleanField(_l('Weekly digest'))
    submit = SubmitField(_l('Save Notification Preferences'))


class DeleteAccountForm(FlaskForm):
    submit = SubmitField(_l('Delete Account'))
