"""
Briefing Notifications

Handles notifications for briefing events like draft ready, approval needed, etc.
Uses the shared ResendClient for consistency with other email functionality.
"""

import os
import logging
from typing import Optional, List
from datetime import datetime

logger = logging.getLogger(__name__)


def get_resend_client():
    """
    Get the shared ResendClient instance.

    Returns:
        ResendClient instance or None if not configured
    """
    try:
        from app.brief.email_client import ResendClient
        return ResendClient()
    except ValueError as e:
        # RESEND_API_KEY not configured
        logger.warning(f"ResendClient not available: {e}")
        return None
    except Exception as e:
        logger.error(f"Error creating ResendClient: {e}")
        return None


def notify_draft_ready(brief_run_id: int) -> dict:
    """
    Send notification when a brief run draft is ready for approval.

    Args:
        brief_run_id: ID of the BriefRun that's ready

    Returns:
        Dict with keys: success, sent_to, error
    """
    from app.models import BriefRun, Briefing, User
    from flask import url_for, current_app

    try:
        brief_run = db.session.get(BriefRun, brief_run_id)
        if not brief_run:
            return {'success': False, 'error': 'BriefRun not found'}

        briefing = brief_run.briefing
        if not briefing:
            return {'success': False, 'error': 'Briefing not found'}

        # Only notify if approval is required
        if briefing.mode != 'approval_required':
            logger.debug(f"Skipping notification for briefing {briefing.id} - auto_send mode")
            return {'success': True, 'sent_to': [], 'skipped': 'auto_send mode'}

        # Find users to notify (owner or org members)
        recipients = []

        if briefing.owner_type == 'user':
            owner = db.session.get(User, briefing.owner_id)
            if owner and owner.email:
                recipients.append({
                    'email': owner.email,
                    'name': owner.username or owner.email
                })
        elif briefing.owner_type == 'org':
            # Get org admins/members
            from app.models import CompanyProfile
            org = db.session.get(CompanyProfile, briefing.owner_id)
            if org and org.user:
                recipients.append({
                    'email': org.user.email,
                    'name': org.user.username or org.user.email
                })

        if not recipients:
            logger.warning(f"No recipients found for draft notification (briefing {briefing.id})")
            return {'success': False, 'error': 'No recipients found'}

        # Generate edit URL
        try:
            with current_app.app_context():
                edit_url = url_for(
                    'briefing.edit_run',
                    briefing_id=briefing.id,
                    run_id=brief_run.id,
                    _external=True
                )
        except RuntimeError:
            # Outside of app context, use a placeholder
            edit_url = f"/briefings/{briefing.id}/runs/{brief_run.id}/edit"

        # Send notification emails
        sent_to = []
        for recipient in recipients:
            success = _send_draft_notification_email(
                recipient_email=recipient['email'],
                recipient_name=recipient['name'],
                briefing_name=briefing.name,
                scheduled_date=brief_run.scheduled_at,
                edit_url=edit_url,
                item_count=len(brief_run.items) if brief_run.items else 0
            )
            if success:
                sent_to.append(recipient['email'])

        logger.info(f"Draft notification sent to {len(sent_to)} recipients for BriefRun {brief_run_id}")
        return {'success': True, 'sent_to': sent_to}

    except Exception as e:
        logger.error(f"Error sending draft notification: {e}", exc_info=True)
        return {'success': False, 'error': str(e)}


def _send_draft_notification_email(
    recipient_email: str,
    recipient_name: str,
    briefing_name: str,
    scheduled_date: Optional[datetime],
    edit_url: str,
    item_count: int
) -> bool:
    """
    Send the actual draft notification email using shared ResendClient.

    Returns:
        True if sent successfully, False otherwise
    """
    client = get_resend_client()
    if not client:
        logger.error("ResendClient not available for draft notification")
        return False

    # Format date
    date_str = scheduled_date.strftime('%B %d, %Y') if scheduled_date else 'your scheduled time'

    # Build email content
    subject = f"Draft Ready: {briefing_name} - {date_str}"

    html_content = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
        <div style="background-color: #f8fafc; border-radius: 8px; padding: 24px; margin-bottom: 24px;">
            <h1 style="margin: 0 0 8px 0; font-size: 24px; color: #1e40af;">Draft Ready for Review</h1>
            <p style="margin: 0; color: #64748b;">Your briefing needs your approval before sending.</p>
        </div>

        <p>Hi {recipient_name},</p>

        <p>A new draft of <strong>{briefing_name}</strong> is ready for your review.</p>

        <div style="background-color: #f1f5f9; border-radius: 8px; padding: 16px; margin: 24px 0;">
            <p style="margin: 0 0 8px 0;"><strong>Scheduled for:</strong> {date_str}</p>
            <p style="margin: 0;"><strong>Topics covered:</strong> {item_count} items</p>
        </div>

        <p>Please review the draft, make any necessary edits, and approve it for sending.</p>

        <div style="text-align: center; margin: 32px 0;">
            <a href="{edit_url}"
               style="display: inline-block; background-color: #2563eb; color: white; padding: 12px 24px; border-radius: 6px; text-decoration: none; font-weight: 500;">
                Review & Approve Draft
            </a>
        </div>

        <p style="color: #64748b; font-size: 14px;">
            If the button doesn't work, copy and paste this link into your browser:<br>
            <a href="{edit_url}" style="color: #2563eb;">{edit_url}</a>
        </p>

        <hr style="border: none; border-top: 1px solid #e2e8f0; margin: 24px 0;">

        <p style="color: #94a3b8; font-size: 12px; margin: 0;">
            This notification was sent because you have approval required enabled for this briefing.
            You can change this in your briefing settings.
        </p>
    </body>
    </html>
    """

    try:
        from_email = os.environ.get('BRIEF_FROM_EMAIL', 'hello@brief.societyspeaks.io')
        from_name = os.environ.get('BRIEF_FROM_NAME', 'Society Speaks Briefings')

        email_data = {
            'from': f'{from_name} <{from_email}>',
            'to': [recipient_email],
            'subject': subject,
            'html': html_content
        }

        # Use ResendClient's retry logic
        success = client._send_with_retry(email_data)

        if success:
            logger.info(f"Draft notification sent to {recipient_email}")
        else:
            logger.error(f"Failed to send draft notification to {recipient_email}")

        return success

    except Exception as e:
        logger.error(f"Failed to send draft notification to {recipient_email}: {e}")
        return False


def notify_brief_sent(brief_run_id: int, recipient_count: int) -> dict:
    """
    Send notification when a brief has been sent to recipients.
    Optional - for informing the owner that their brief was delivered.

    Args:
        brief_run_id: ID of the BriefRun that was sent
        recipient_count: Number of recipients it was sent to

    Returns:
        Dict with keys: success, error
    """
    # This is optional - implement if needed
    # For now, just log it
    logger.info(f"BriefRun {brief_run_id} sent to {recipient_count} recipients")
    return {'success': True}
