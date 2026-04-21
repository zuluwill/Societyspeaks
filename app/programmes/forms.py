from flask_wtf import FlaskForm
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, Optional, URL

from app.discussions.forms import country_choices
from flask_babel import lazy_gettext as _l

PROGRAMME_VISIBILITY_CHOICES = [
    ('public', 'Public (listed)'),
    ('unlisted', 'Unlisted (link access)'),
    ('invite_only', 'Invite-only participants'),
    ('private', 'Private (owners/stewards only)'),
]


class ProgrammeForm(FlaskForm):
    name = StringField(_l('Programme Name'), validators=[DataRequired(), Length(min=3, max=200)])
    description = TextAreaField(_l('Description'), validators=[Optional(), Length(max=5000)])
    geographic_scope = SelectField(
        _l('Geographic Scope'),
        choices=[('global', _l('Global')), ('country', _l('Country'))],
        validators=[DataRequired()]
    )
    country = SelectField(_l('Country'), choices=country_choices, validators=[Optional()])
    logo_url = StringField(_l('Logo URL'), validators=[Optional(), URL(), Length(max=255)])

    themes_csv = TextAreaField(
        _l('Themes (comma separated)'),
        validators=[Optional(), Length(max=2000)],
        description=_l('Example: Health, Prosperity, Security')
    )
    phases_csv = TextAreaField(
        _l('Phases (comma separated)'),
        validators=[Optional(), Length(max=2000)],
        description=_l('Example: Agenda-setting, Wave 1, Wave 2')
    )
    cohorts_text = TextAreaField(
        _l('Cohorts (one per line: slug|Label)'),
        validators=[Optional(), Length(max=4000)],
        description=_l('Example line: pilot-informed|Pilot (informed)')
    )

    owner_type = SelectField(
        _l('Owner'),
        choices=[('user', _l('My account')), ('company', _l('Organization'))],
        validators=[DataRequired()]
    )
    company_profile_id = SelectField(_l('Organization'), coerce=int, validators=[Optional()])
    visibility = SelectField(
        _l('Visibility'),
        choices=PROGRAMME_VISIBILITY_CHOICES,
        validators=[DataRequired()],
        default='public'
    )

    submit = SubmitField(_l('Save Programme'))


class InviteStewardForm(FlaskForm):
    email = StringField(_l('Steward Email'), validators=[DataRequired(), Email(), Length(max=150)])
    submit = SubmitField(_l('Invite Steward'))


class InviteProgrammeAccessForm(FlaskForm):
    email = StringField(_l('Participant Email'), validators=[DataRequired(), Email(), Length(max=150)])
    submit = SubmitField(_l('Grant access'))
