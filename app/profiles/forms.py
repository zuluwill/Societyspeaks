# app/profiles/forms.py
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, URLField, SubmitField
from wtforms.validators import DataRequired, Optional, URL, Email
from flask_wtf.file import FileField, FileAllowed

class IndividualProfileForm(FlaskForm):
    full_name = StringField('Full Name', validators=[DataRequired()])
    bio = TextAreaField('Bio', validators=[Optional()])
    location = StringField('Location', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    website = URLField('Website', validators=[Optional(), URL()])
    social_links = TextAreaField('Social Links', validators=[Optional()])
    profile_image = FileField('Profile Picture', validators=[Optional(), FileAllowed(['jpg', 'png'], 'Images only!')])
    banner_image = FileField('Banner Image', validators=[Optional(), FileAllowed(['jpg', 'png'], 'Images only!')])
    submit = SubmitField('Create Profile')

class CompanyProfileForm(FlaskForm):
    company_name = StringField('Company Name', validators=[DataRequired()])
    description = TextAreaField('Company Description', validators=[Optional()])
    location = StringField('Location', validators=[Optional()])
    email = StringField('Email', validators=[Optional(), Email()])
    website = URLField('Website', validators=[Optional(), URL()])
    social_links = TextAreaField('Social Links', validators=[Optional()])
    profile_image = FileField('Company Logo', validators=[Optional(), FileAllowed(['jpg', 'png'], 'Images only!')])
    banner_image = FileField('Banner Image', validators=[Optional(), FileAllowed(['jpg', 'png'], 'Images only!')])
    submit = SubmitField('Create Company Profile')