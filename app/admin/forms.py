# app/admin/forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, URLField, SubmitField, 
    SelectField, RadioField, BooleanField, PasswordField
)
from wtforms.validators import DataRequired, Optional, URL, Email, Length, EqualTo
from flask_wtf.file import FileField, FileAllowed
from app.models import User

class UserAssignmentForm(FlaskForm):
    assignment_type = RadioField(
        'Assignment Type',
        choices=[
            ('existing', 'Assign to Existing User'),
            ('new', 'Create New User')
        ],
        default='existing'
    )

    # Changed from QuerySelectField to SelectField
    existing_user = SelectField(
        'Select Existing User',
        choices=[],  # We'll populate this dynamically
        coerce=int
    )

    username = StringField('Username', validators=[Optional(), Length(min=3, max=50)])
    email = StringField('Email', validators=[Optional(), Email()])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    confirm_password = PasswordField(
        'Confirm Password',
        validators=[Optional(), EqualTo('password', message='Passwords must match')]
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Populate the choices for existing_user
        users = User.query.all()
        self.existing_user.choices = [(user.id, user.username) for user in users]

    def validate(self):
        if not super().validate():
            return False
        if self.assignment_type.data == 'existing':
            if not self.existing_user.data:
                self.existing_user.errors.append('Please select a user')
                return False
        else:  # new user
            if not self.username.data:
                self.username.errors.append('Username is required')
                return False
            if not self.email.data:
                self.email.errors.append('Email is required')
                return False
            if not self.password.data:
                self.password.errors.append('Password is required')
                return False

            if User.query.filter_by(username=self.username.data).first():
                self.username.errors.append('Username already exists')
                return False
            if User.query.filter_by(email=self.email.data).first():
                self.email.errors.append('Email already exists')
                return False
        return True

class UserSearchForm(FlaskForm):
    username = StringField('Username', validators=[Optional()])
    email = StringField('Email', validators=[Optional()])
    status = SelectField(
        'Status',
        choices=[('', 'All'), ('active', 'Active'), ('inactive', 'Inactive')],
        validators=[Optional()]
    )
    profile_type = SelectField(
        'Profile Type',
        choices=[
            ('', 'All'), 
            ('individual', 'Individual'),
            ('company', 'Company'), 
            ('none', 'No Profile')
        ],
        validators=[Optional()]
    )
    submit = SubmitField('Search')

class AdminSettingsForm(FlaskForm):
    enable_user_registration = BooleanField('Enable User Registration')
    enable_public_profiles = BooleanField('Enable Public Profiles')
    maintenance_mode = BooleanField('Maintenance Mode')
    maintenance_message = TextAreaField('Maintenance Message')
    support_email = StringField('Support Email', validators=[Optional(), Email()])
    terms_url = URLField('Terms of Service URL', validators=[Optional(), URL()])
    privacy_url = URLField('Privacy Policy URL', validators=[Optional(), URL()])
    submit = SubmitField('Save Settings')