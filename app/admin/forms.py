# app/admin/forms.py
from flask_wtf import FlaskForm
from wtforms import (
    StringField, TextAreaField, URLField, SubmitField,
    SelectField, RadioField, BooleanField, PasswordField
)
from wtforms.validators import DataRequired, Optional, URL, Email, Length, EqualTo
from flask_wtf.file import FileField, FileAllowed
from app.models import User
from app.programmes.forms import PROGRAMME_VISIBILITY_CHOICES

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

class AdminProgrammeForm(FlaskForm):
    name = StringField('Programme Name', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()])
    geographic_scope = SelectField(
        'Geographic Scope',
        choices=[('global', 'Global'), ('country', 'Country'), ('city', 'City')],
        default='country'
    )
    country = StringField('Country', validators=[Optional(), Length(max=100)])
    logo_url = URLField('Logo URL', validators=[Optional(), URL(), Length(max=255)])
    themes = StringField('Themes (comma-separated)', validators=[Optional()])
    visibility = SelectField(
        'Visibility',
        choices=PROGRAMME_VISIBILITY_CHOICES,
        validators=[DataRequired()],
        default='public'
    )
    submit = SubmitField('Create Programme')


class AdminOrgMemberForm(FlaskForm):
    assignment_type = RadioField(
        'User',
        choices=[('existing', 'Existing User'), ('new', 'Create New User')],
        default='existing'
    )
    existing_user = SelectField('Select User', choices=[], coerce=int)
    username = StringField('Username', validators=[Optional(), Length(min=3, max=50)])
    email = StringField('Email', validators=[Optional(), Email()])
    password = PasswordField('Password', validators=[Optional(), Length(min=6)])
    role = SelectField(
        'Role',
        choices=[('admin', 'Admin'), ('editor', 'Editor'), ('viewer', 'Viewer')],
        default='admin'
    )
    submit = SubmitField('Add Member')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        users = User.query.order_by(User.username).all()
        self.existing_user.choices = [(u.id, f'{u.username} ({u.email})') for u in users]

    def validate(self):
        if not super().validate():
            return False
        if self.assignment_type.data == 'existing':
            if not self.existing_user.data:
                self.existing_user.errors.append('Please select a user.')
                return False
        else:
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


class AdminSettingsForm(FlaskForm):
    enable_user_registration = BooleanField('Enable User Registration')
    enable_public_profiles = BooleanField('Enable Public Profiles')
    maintenance_mode = BooleanField('Maintenance Mode')
    maintenance_message = TextAreaField('Maintenance Message')
    support_email = StringField('Support Email', validators=[Optional(), Email()])
    terms_url = URLField('Terms of Service URL', validators=[Optional(), URL()])
    privacy_url = URLField('Privacy Policy URL', validators=[Optional(), URL()])
    submit = SubmitField('Save Settings')