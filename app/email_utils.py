# app/email_utils.py
import os
import requests
from flask import current_app, url_for
from app.models import Discussion, IndividualProfile, CompanyProfile


#This function is responsible for sending events to Loops
def send_loops_event(email_address, event_name, user_id, contact_properties, event_properties):
    api_key = os.getenv('LOOPS_API_KEY')
    url = f'https://app.loops.so/api/v1/events/{event_name}'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'email': email_address,
        'userId': user_id,
        'contactProperties': contact_properties,
        'eventProperties': event_properties
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        current_app.logger.info(f"Loops event '{event_name}' triggered for {email_address}.")
    else:
        current_app.logger.error(f"Failed to trigger Loops event '{event_name}' for {email_address}: {response.status_code} - {response.text}")



#This function sends transactional emails through Loops
def send_email(recipient_email, data_variables, transactional_id):
    api_key = os.getenv('LOOPS_API_KEY')
    url = 'https://app.loops.so/api/v1/transactional'

    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }

    payload = {
        'transactionalId': transactional_id,
        'email': recipient_email,
        'dataVariables': data_variables
    }

    response = requests.post(url, json=payload, headers=headers)

    if response.status_code == 200:
        current_app.logger.info(f"Email sent successfully to {recipient_email}.")
    else:
        current_app.logger.error(f"Failed to send email to {recipient_email}: {response.status_code} - {response.text}")




#send a password reset email
def send_password_reset_email(user, token):
    # Transactional ID for the password reset email
    transactional_id = "cm34ll2e604fmynht3l8jns9p"

    # Generate the reset URL
    reset_url = url_for('auth.password_reset', token=token, _external=True)

    # Prepare data variables
    data_variables = {
        "username": user.username or "User",  # Use username as fallback
        "resetUrl": reset_url
    }

    # Send the email with the reset link
    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



#sending a welcome email.
def send_welcome_email(user):
    # Set the transactional ID for the welcome email
    transactional_id = "cm34nogvo006fxuem1vk61fjd"  # Alternatively, you can fetch this from an environment variable

    # Prepare data variables for the email
    data_variables = {
        "username": user.username or "There"  # Fallback to "There" if first name is not provided
    }

    # Call the send_email function with the transactional ID and data variables
    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



#account activation email. although i havent implemented this yet in registration as i thought it overkill at this stage
def send_account_activation_email(user, activation_token):
    transactional_id = "cm34oe3y003sa11ew5rw10mi6"  # ID for account activation email

    activation_url = url_for('auth.activate_account', token=activation_token, _external=True)

    # Prepare data variables for the email
    data_variables = {
        "username": user.username or "User",
        "activationUrl": activation_url
    }

    send_email(
        recipient_email=user.email,
        data_variables=data_variables,
        transactional_id=transactional_id
    )



def get_user_discussions_summary(user):
    # Query discussions created by the user
    discussions = Discussion.query.filter_by(creator_id=user.id).all()

    # Format discussions into a single string with title and views only
    discussion_summary = "\n".join([
        f"- {discussion.title}: {discussion.views.count()} views"
        for discussion in discussions
    ])

    return discussion_summary

def send_discussion_update_email(user, summary_period="Weekly"):
    # Gather formatted discussion summary for the user
    discussion_summary = get_user_discussions_summary(user)

    # Prepare event payload
    event_properties = {
        "summaryPeriod": summary_period,
        "discussions": discussion_summary  # Pass formatted discussion summary as a single string
    }

    # Trigger the Loops event
    send_loops_event(
        email_address=user.email,
        event_name="weekly_discussion_update",
        user_id=user.id,
        contact_properties={
            "username": user.username
        },
        event_properties=event_properties
    )



def get_missing_individual_profile_fields(profile):
    missing_fields = []
    if not profile.full_name:
        missing_fields.append("Full Name")
    if not profile.bio:
        missing_fields.append("Bio")
    if not profile.city:
        missing_fields.append("City")
    if not profile.country:
        missing_fields.append("Country")
    if not profile.profile_image:
        missing_fields.append("Profile Image")
    return missing_fields

def get_missing_company_profile_fields(profile):
    missing_fields = []
    if not profile.company_name:
        missing_fields.append("Company Name")
    if not profile.description:
        missing_fields.append("Description")
    if not profile.city:
        missing_fields.append("City")
    if not profile.country:
        missing_fields.append("Country")
    if not profile.logo:
        missing_fields.append("Company Logo")
    return missing_fields



def send_profile_completion_reminder_email(user):
    profile = user.individual_profile or user.company_profile

    if isinstance(profile, IndividualProfile):
        missing_fields = get_missing_individual_profile_fields(profile)
    elif isinstance(profile, CompanyProfile):
        missing_fields = get_missing_company_profile_fields(profile)
    else:
        return

    if missing_fields:
        # Generate profile link
        profile_link = url_for('profiles.view_profile', username=user.username, _external=True)


        # Prepare event properties
        event_properties = {
            "profileLink": profile_link,
            "missingFields": "\n".join(f"- {field}" for field in missing_fields)  # Format as bullet points
        }

        # Trigger the profile completion reminder event in Loops
        send_loops_event(
            email_address=user.email,
            event_name="profile_completion_reminder",  # Use the exact event name set up in Loops
            user_id=user.id,
            contact_properties={
                "username": user.username  # Adjust based on whether you have username or first_name
            },
            event_properties=event_properties
        )
