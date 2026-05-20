"""
Briefing Notifications

Handles notifications for briefing events like draft ready, approval needed, etc.
Uses the shared ResendClient for consistency with other email functionality.
"""

import os
import logging
from typing import Optional, List
from datetime import datetime
from flask_babel import gettext as _

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
    from app import db
    from app.models import BriefRun, Briefing, User
    from app.briefing.briefing_locale import resolve_briefing_locale
    from flask import url_for, current_app

    try:
        brief_run = db.session.get(BriefRun, brief_run_id)
        if not brief_run:
            return {'success': False, 'error': _('BriefRun not found')}

        briefing = brief_run.briefing
        if not briefing:
            return {'success': False, 'error': _('Briefing not found')}

        # Notify whenever a brief is sitting in the approval queue and the
        # owner needs to act on it. That covers two cases:
        #   1. mode='approval_required' — every run waits for approval.
        #   2. mode='auto_send' — quality gate has *held* a run that would
        #      otherwise have shipped; the owner needs to know it's there.
        # Approved runs and silent failures are handled elsewhere.
        if brief_run.status not in ('generated_draft', 'awaiting_approval'):
            logger.debug(
                f"Skipping draft notification for BriefRun {brief_run.id} — "
                f"status is {brief_run.status}, nothing to action."
            )
            return {'success': True, 'sent_to': [], 'skipped': f'status:{brief_run.status}'}

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
            return {'success': False, 'error': _('No recipients found')}

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
        # Only the quality-gate hold path populates failure_reason on an
        # otherwise-readable run; pass it through so the email can explain
        # *why* this is in the approval queue rather than just "draft ready".
        hold_reason = brief_run.failure_reason if brief_run.status == 'awaiting_approval' else None
        locale_str = resolve_briefing_locale(briefing)
        for recipient in recipients:
            success = _send_draft_notification_email(
                recipient_email=recipient['email'],
                recipient_name=recipient['name'],
                briefing_name=briefing.name,
                scheduled_date=brief_run.scheduled_at,
                edit_url=edit_url,
                item_count=len(brief_run.items) if brief_run.items else 0,
                hold_reason=hold_reason,
                locale_str=locale_str,
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
    item_count: int,
    hold_reason: Optional[str] = None,
    locale_str: str = 'en',
) -> bool:
    """Send the draft/held-brief notification using a gettext-aware template."""
    from flask import render_template
    from flask_babel import force_locale, gettext as _, format_datetime
    from app.lib.locale_utils import email_html_locale_kwargs

    client = get_resend_client()
    if not client:
        logger.error("ResendClient not available for draft notification")
        return False

    is_held = bool(hold_reason)

    with force_locale(locale_str):
        date_str = (
            format_datetime(scheduled_date, format='long')
            if scheduled_date else _('your scheduled time')
        )
        if is_held:
            headline = _('Brief held for your review')
            sub_headline = _(
                "We held today's brief back because the quality gate caught a problem."
            )
            subject = _('Action needed: %(briefing)s — %(date)s', briefing=briefing_name, date=date_str)
            cta_text = _('Review and send (or skip)')
        else:
            headline = _('Draft ready for review')
            sub_headline = _('Your briefing needs your approval before sending.')
            subject = _('Draft ready: %(briefing)s — %(date)s', briefing=briefing_name, date=date_str)
            cta_text = _('Review & Approve Draft')

        html_content = render_template(
            'emails/brief_draft_ready.html',
            **email_html_locale_kwargs(locale_str),
            recipient_name=recipient_name,
            briefing_name=briefing_name,
            date_str=date_str,
            item_count=item_count,
            hold_reason=hold_reason,
            edit_url=edit_url,
            headline=headline,
            sub_headline=sub_headline,
            cta_text=cta_text,
            is_held=is_held,
        )

    try:
        from app.lib.brief_from_email import brief_from_email_address
        from_email = brief_from_email_address()
        from_name = os.environ.get('BRIEF_FROM_NAME', 'Society Speaks Briefings')

        email_data = {
            'from': f'{from_name} <{from_email}>',
            'to': [recipient_email],
            'subject': subject,
            'html': html_content,
        }

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
