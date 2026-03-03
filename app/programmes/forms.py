from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, URL

from app.discussions.forms import country_choices

PROGRAMME_VISIBILITY_CHOICES = [
    ('public', 'Public (listed)'),
    ('unlisted', 'Unlisted (link access)'),
    ('invite_only', 'Invite-only participants'),
    ('private', 'Private (owners/stewards only)'),
]


class ProgrammeForm(FlaskForm):
    name = StringField('Programme Name', validators=[DataRequired(), Length(min=3, max=200)])
    description = TextAreaField('Description', validators=[Optional(), Length(max=5000)])
    geographic_scope = SelectField(
        'Geographic Scope',
        choices=[('global', 'Global'), ('country', 'Country')],
        validators=[DataRequired()]
    )
    country = SelectField('Country', choices=country_choices, validators=[Optional()])
    logo_url = StringField('Logo URL', validators=[Optional(), URL(), Length(max=255)])

    themes_csv = TextAreaField(
        'Themes (comma separated)',
        validators=[Optional(), Length(max=2000)],
        description='Example: Health, Prosperity, Security'
    )
    phases_csv = TextAreaField(
        'Phases (comma separated)',
        validators=[Optional(), Length(max=2000)],
        description='Example: Agenda-setting, Wave 1, Wave 2'
    )
    cohorts_text = TextAreaField(
        'Cohorts (one per line: slug|Label)',
        validators=[Optional(), Length(max=4000)],
        description='Example line: pilot-informed|Pilot (informed)'
    )

    owner_type = SelectField(
        'Owner',
        choices=[('user', 'My account'), ('company', 'Organization')],
        validators=[DataRequired()]
    )
    company_profile_id = SelectField('Organization', coerce=int, validators=[Optional()])
    visibility = SelectField(
        'Visibility',
        choices=PROGRAMME_VISIBILITY_CHOICES,
        validators=[DataRequired()],
        default='public'
    )

    submit = SubmitField('Save Programme')


class InviteStewardForm(FlaskForm):
    email = StringField('Steward Email', validators=[DataRequired(), Email(), Length(max=150)])
    submit = SubmitField('Invite Steward')


class InviteProgrammeAccessForm(FlaskForm):
    email = StringField('Participant Email', validators=[DataRequired(), Email(), Length(max=150)])
    submit = SubmitField('Grant access')
