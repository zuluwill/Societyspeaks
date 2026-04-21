# app/discussions/statement_forms.py
"""
Forms for Native Statement System

Based on pol.is patterns with enhancements for Society Speaks
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, RadioField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange
from flask_babel import lazy_gettext as _l


class StatementForm(FlaskForm):
    """Form for creating a new statement"""
    content = TextAreaField(_l('Statement'), validators=[
        DataRequired(message=_l("Statement is required")),
        Length(min=10, max=500, message=_l("Statement must be 10-500 characters"))
    ])
    statement_type = RadioField(_l('Type'), choices=[
        ('claim', _l('Claim')),
        ('question', _l('Question'))
    ], default='claim', validators=[DataRequired()])
    submit = SubmitField(_l('Post Statement'))


class VoteForm(FlaskForm):
    """Form for voting on a statement (used for CSRF protection)"""
    vote = IntegerField(_l('Vote'), validators=[
        DataRequired(),
        NumberRange(min=-1, max=1, message=_l("Vote must be -1, 0, or 1"))
    ])
    confidence = IntegerField(_l('Confidence'), validators=[
        Optional(),
        NumberRange(min=1, max=5, message=_l("Confidence must be between 1 and 5"))
    ])


class ResponseForm(FlaskForm):
    """Form for adding a threaded response to a statement"""
    content = TextAreaField(_l('Response'), validators=[
        DataRequired(message=_l("Response is required")),
        Length(min=10, max=2000, message=_l("Response must be 10-2000 characters"))
    ])
    position = RadioField(_l('Position'), choices=[
        ('pro', _l('Supporting')),
        ('con', _l('Opposing')),
        ('neutral', _l('Neutral/Clarifying'))
    ], validators=[DataRequired()])
    submit = SubmitField(_l('Post Response'))


class EvidenceForm(FlaskForm):
    """Form for adding evidence to a response"""
    source_title = StringField(_l('Source Title'), validators=[
        DataRequired(),
        Length(max=500)
    ])
    source_url = StringField(_l('Source URL'), validators=[
        Optional(),
        Length(max=1000)
    ])
    citation = TextAreaField(_l('Citation'), validators=[
        Optional(),
        Length(max=1000)
    ])
    submit = SubmitField(_l('Add Evidence'))


class FlagStatementForm(FlaskForm):
    """Form for flagging a statement for moderation"""
    flag_reason = SelectField(_l('Reason'), choices=[
        ('spam', _l('Spam')),
        ('offensive', _l('Offensive/Abusive')),
        ('off_topic', _l('Off Topic')),
        ('duplicate', _l('Duplicate'))
    ], validators=[DataRequired()])
    additional_context = TextAreaField(_l('Additional Context'), validators=[
        Optional(),
        Length(max=1000)
    ])
    submit = SubmitField(_l('Flag Statement'))

