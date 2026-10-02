from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from wtforms import BooleanField, IntegerField, StringField, TextAreaField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional


class StartForm(FlaskForm):
    email = StringField(_l('Work email'), validators=[DataRequired(), Email(), Length(max=150)])


class QuestionForm(FlaskForm):
    question = StringField(
        _l('What do you want to know?'),
        validators=[
            DataRequired(message=_l('Write the question you want your audience to answer.')),
            Length(min=15, max=300, message=_l('Use between 15 and 300 characters.')),
        ],
    )
    organisation_name = StringField(
        _l('Your organisation'),
        validators=[DataRequired(message=_l('Tell participants who is asking.')), Length(max=200)],
    )
    audience_label = StringField(_l('Who will take part?'), validators=[Optional(), Length(max=200)])
    audience_size = IntegerField(
        _l('Roughly how many people will you invite?'),
        validators=[Optional(), NumberRange(min=1, max=10_000_000)],
    )
    context = TextAreaField(_l('Background'), validators=[Optional(), Length(max=6000)])


class SettingsForm(FlaskForm):
    open_days = IntegerField(
        _l('How many days should it stay open?'),
        validators=[DataRequired(), NumberRange(min=1, max=90)],
    )
    allow_audience_statements = BooleanField(_l('Let participants suggest statements'))
    show_results_to_participants = BooleanField(_l('Show participants how others voted when they finish'))


class ActionForm(FlaskForm):
    """CSRF only: for buttons that post with no fields."""
