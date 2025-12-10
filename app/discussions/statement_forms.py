# app/discussions/statement_forms.py
"""
Forms for Native Statement System

Based on pol.is patterns with enhancements for Society Speaks
"""
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SelectField, RadioField, SubmitField, IntegerField
from wtforms.validators import DataRequired, Length, Optional, NumberRange


class StatementForm(FlaskForm):
    """Form for creating a new statement"""
    content = TextAreaField('Statement', validators=[
        DataRequired(message="Statement is required"),
        Length(min=10, max=500, message="Statement must be 10-500 characters")
    ])
    statement_type = SelectField('Type', choices=[
        ('claim', 'Claim'),
        ('question', 'Question')
    ], default='claim')
    submit = SubmitField('Post Statement')


class VoteForm(FlaskForm):
    """Form for voting on a statement (used for CSRF protection)"""
    vote = IntegerField('Vote', validators=[
        DataRequired(),
        NumberRange(min=-1, max=1, message="Vote must be -1, 0, or 1")
    ])
    confidence = IntegerField('Confidence', validators=[
        Optional(),
        NumberRange(min=1, max=5, message="Confidence must be between 1 and 5")
    ])


class ResponseForm(FlaskForm):
    """Form for adding a threaded response to a statement"""
    content = TextAreaField('Response', validators=[
        DataRequired(message="Response is required"),
        Length(min=10, max=2000, message="Response must be 10-2000 characters")
    ])
    position = RadioField('Position', choices=[
        ('pro', 'Supporting'),
        ('con', 'Opposing'),
        ('neutral', 'Neutral/Clarifying')
    ], validators=[DataRequired()])
    submit = SubmitField('Post Response')


class EvidenceForm(FlaskForm):
    """Form for adding evidence to a response"""
    source_title = StringField('Source Title', validators=[
        DataRequired(),
        Length(max=500)
    ])
    source_url = StringField('Source URL', validators=[
        Optional(),
        Length(max=1000)
    ])
    citation = TextAreaField('Citation', validators=[
        Optional(),
        Length(max=1000)
    ])
    submit = SubmitField('Add Evidence')


class FlagStatementForm(FlaskForm):
    """Form for flagging a statement for moderation"""
    flag_reason = SelectField('Reason', choices=[
        ('spam', 'Spam'),
        ('offensive', 'Offensive/Abusive'),
        ('off_topic', 'Off Topic'),
        ('duplicate', 'Duplicate')
    ], validators=[DataRequired()])
    additional_context = TextAreaField('Additional Context', validators=[
        Optional(),
        Length(max=1000)
    ])
    submit = SubmitField('Flag Statement')

