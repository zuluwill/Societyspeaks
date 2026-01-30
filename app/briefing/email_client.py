"""
Briefing Email Client

Extends ResendClient for sending BriefRun emails to recipients.
Reuses existing email infrastructure with briefing-specific logic.
"""

import os
import logging
from datetime import datetime
from typing import Dict, List, Optional
from flask import render_template, current_app
from sqlalchemy import update
from app import db
from app.models import BriefRun, BriefRecipient, Briefing, SendingDomain
from app.resend_client import ResendEmailClient as BaseResendClient
from app.storage_utils import get_base_url

logger = logging.getLogger(__name__)


def _mark_brief_run_sent(brief_run: BriefRun, reason: str = "sent") -> bool:
    """
    Atomically mark a BriefRun as sent using UPDATE with WHERE clause.

    This prevents race conditions where multiple processes might try to
    mark the same BriefRun as sent simultaneously (TOCTOU vulnerability).

    Args:
        brief_run: BriefRun instance to mark as sent
        reason: Reason for marking as sent (for logging)

    Returns:
        True if this process successfully marked it as sent,
        False if another process already marked it
    """
    try:
        result = db.session.execute(
            update(BriefRun)
            .where(BriefRun.id == brief_run.id)
            .where(BriefRun.sent_at == None)  # noqa: E711 - SQLAlchemy requires == None
            .values(sent_at=datetime.utcnow(), status='sent')
        )
        db.session.commit()

        if result.rowcount == 0:
            # Another process already marked it - refresh to get actual sent_at
            db.session.refresh(brief_run)
            logger.warning(
                f"BriefRun {brief_run.id} already sent at {brief_run.sent_at} by another process. "
                f"Reason for this attempt: {reason}"
            )
            return False

        logger.info(f"BriefRun {brief_run.id} marked as sent ({reason})")
        return True

    except Exception as e:
        logger.error(f"Failed to mark BriefRun {brief_run.id} as sent: {e}")
        db.session.rollback()
        return False


class BriefingEmailClient:
    """
    Email client for Briefing system.
    Extends base ResendClient with briefing-specific functionality.
    """
    
    def __init__(self):
        self.base_client = BaseResendClient()
        # Rate limiting is handled by base_client
    
    def send_brief_run(
        self,
        brief_run: BriefRun,
        recipient: BriefRecipient
    ) -> bool:
        """
        Send BriefRun email to a recipient.
        
        Args:
            brief_run: BriefRun instance to send
            recipient: BriefRecipient instance
        
        Returns:
            bool: True if sent successfully
        """
        try:
            # Get briefing for configuration
            briefing = brief_run.briefing
            
            # Determine from_email (custom domain or default)
            from_email = self._get_from_email(briefing)
            from_name = briefing.from_name or briefing.name
            
            # Render email HTML
            html_content = self._render_brief_run_email(brief_run, recipient, briefing)
            
            # Build unsubscribe URL
            base_url = get_base_url()
            unsubscribe_url = f"{base_url}/briefings/{briefing.id}/unsubscribe/{recipient.magic_token or ''}"
            
            # Prepare email data
            email_data = {
                'from': f"{from_name} <{from_email}>",
                'to': [recipient.email],
                'subject': self._generate_subject(brief_run, briefing),
                'html': html_content,
                'headers': {
                    'List-Unsubscribe': f'<{unsubscribe_url}>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
                }
            }
            
            # Send via base client (handles rate limiting internally)
            success = self.base_client._send_with_retry(email_data)
            
            if success:
                logger.info(f"Sent BriefRun {brief_run.id} to {recipient.email}")
                
                # Record analytics event
                try:
                    from app.lib.email_analytics import EmailAnalytics
                    EmailAnalytics.record_send(
                        email=recipient.email,
                        category=EmailAnalytics.CATEGORY_DAILY_BRIEF,
                        subject=self._generate_subject(brief_run, briefing)
                    )
                except Exception as analytics_error:
                    logger.warning(f"Failed to record analytics for {recipient.email}: {analytics_error}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to send BriefRun {brief_run.id} to {recipient.email}: {e}", exc_info=True)
            return False
    
    def _get_from_email(self, briefing: Briefing) -> str:
        """
        Get from_email for briefing (custom domain or default).
        
        Args:
            briefing: Briefing instance
        
        Returns:
            str: From email address
        """
        # Check if briefing has custom sending domain
        # Re-check domain status right before sending to handle race conditions
        # Use try/except to handle case where domain is deleted mid-send
        try:
            if briefing.sending_domain_id:
                # Reload domain to ensure it still exists (handles deletion race condition)
                domain = SendingDomain.query.get(briefing.sending_domain_id)
                if domain and domain.status == 'verified' and briefing.from_email:
                    # Use custom domain email
                    return briefing.from_email
                # If domain doesn't exist, not verified, or from_email not set, fall through to default
        except Exception as e:
            logger.warning(f"Error checking domain for briefing {briefing.id}: {e}")
            # Fall through to default on any error
        
        # Fallback to default (just the email address, name is set separately via from_name)
        from_email = os.environ.get('BRIEF_FROM_EMAIL', 'hello@brief.societyspeaks.io')
        # Handle case where env var might include name (extract just the email)
        if '<' in from_email and '>' in from_email:
            # Extract email from format "Name <email>"
            import re
            match = re.search(r'<([^>]+)>', from_email)
            if match:
                return match.group(1)
        return from_email
    
    def _generate_subject(self, brief_run: BriefRun, briefing: Briefing) -> str:
        """Generate email subject line"""
        scheduled_date = brief_run.scheduled_at.strftime('%B %d, %Y') if brief_run.scheduled_at else 'Today'
        return f"{briefing.name} - {scheduled_date}"
    
    def _render_brief_run_email(
        self,
        brief_run: BriefRun,
        recipient: BriefRecipient,
        briefing: Briefing
    ) -> str:
        """
        Render BriefRun email HTML.
        
        Args:
            brief_run: BriefRun instance
            recipient: BriefRecipient instance
            briefing: Briefing configuration
        
        Returns:
            str: HTML email content
        """
        base_url = get_base_url()
        
        # Use approved content if available, otherwise draft
        content_html = brief_run.approved_html or brief_run.draft_html or ''
        content_markdown = brief_run.approved_markdown or brief_run.draft_markdown or ''
        
        # Build URLs
        view_url = f"{base_url}/briefings/{briefing.id}/runs/{brief_run.id}"
        reader_url = f"{base_url}/briefings/public/{briefing.id}/runs/{brief_run.id}/reader"
        unsubscribe_url = f"{base_url}/briefings/{briefing.id}/unsubscribe/{recipient.magic_token or ''}"
        
        # Get company logo if org briefing
        company_logo_url = None
        if briefing.owner_type == 'org' and briefing.owner_id:
            from app.models import CompanyProfile
            company = CompanyProfile.query.get(briefing.owner_id)
            if company and company.logo:
                # Build full URL for logo
                company_logo_url = f"{base_url}/profiles/image/{company.logo}"
        
        # Get items for template (for audio links)
        items = sorted(brief_run.items, key=lambda x: x.position or 0) if brief_run.items else []
        
        # Check if any items have audio
        has_audio = any(item.audio_url for item in items)
        
        # Try to render template, fallback to simple HTML
        try:
            html = render_template(
                'emails/brief_run.html',
                brief_run=brief_run,
                briefing=briefing,
                recipient=recipient,
                content_html=content_html,
                view_url=view_url,
                reader_url=reader_url,
                unsubscribe_url=unsubscribe_url,
                base_url=base_url,
                company_logo_url=company_logo_url,
                items=items,
                has_audio=has_audio
            )
            return html
        except Exception as e:
            logger.warning(f"Could not render brief_run email template: {e}, using fallback")
            return self._fallback_html(brief_run, briefing, recipient, content_html, unsubscribe_url)
    
    def _fallback_html(
        self,
        brief_run: BriefRun,
        briefing: Briefing,
        recipient: BriefRecipient,
        content_html: str,
        unsubscribe_url: str
    ) -> str:
        """Fallback HTML if template not available"""
        scheduled_date = brief_run.scheduled_at.strftime('%B %d, %Y') if brief_run.scheduled_at else 'Today'
        
        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{briefing.name}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="background: linear-gradient(to bottom, #1e40af, #3b82f6); color: white; padding: 30px 20px; text-align: center; border-radius: 8px 8px 0 0;">
                <h1 style="margin: 0; font-size: 24px;">{briefing.name}</h1>
                <p style="margin: 10px 0 0 0; opacity: 0.9;">{scheduled_date}</p>
            </div>
            <div style="background: white; padding: 30px 20px; border: 1px solid #e5e7eb; border-top: none;">
                {content_html or '<p>No content available.</p>'}
            </div>
            <div style="text-align: center; padding: 20px; color: #6b7280; font-size: 12px;">
                <p><a href="{unsubscribe_url}" style="color: #6b7280;">Unsubscribe</a></p>
                <p>Society Speaks – Sense-making, not sensationalism</p>
            </div>
        </body>
        </html>
        """
    
    def send_brief_run_to_all_recipients(self, brief_run: BriefRun) -> dict:
        """
        Send BriefRun to all active recipients.

        Uses batch sending for efficiency when recipient count exceeds threshold.
        Falls back to individual sending for small lists or when batch fails.
        
        Only sends to recipients who were added BEFORE the brief run was created,
        preventing new recipients from receiving a flood of historical briefs.

        Args:
            brief_run: BriefRun instance

        Returns:
            dict: {'sent': count, 'failed': count, 'method': 'batch'|'individual'}
        """
        briefing = brief_run.briefing
        
        # Only send to recipients who were added before this run was created
        # This prevents new recipients from receiving all historical runs
        # Use scheduled_at as the effective creation time (BriefRun doesn't have created_at field)
        run_timestamp = brief_run.scheduled_at
        recipients = briefing.recipients.filter(
            BriefRecipient.status == 'active',
            BriefRecipient.created_at <= run_timestamp
        ).all()

        total_recipients = len(recipients)
        
        # Handle case where no eligible recipients exist (e.g., all recipients added after run)
        # Mark as sent to prevent infinite retries of old runs
        if total_recipients == 0:
            _mark_brief_run_sent(
                brief_run,
                reason="no eligible recipients - all recipients added after run was created"
            )
            return {'sent': 0, 'failed': 0, 'method': 'none', 'skipped': 'no_eligible_recipients'}

        # Use batch sending for larger recipient lists (threshold: 10+)
        if total_recipients >= 10:
            result = self._send_batch_to_recipients(brief_run, recipients)
        else:
            result = self._send_individual_to_recipients(brief_run, recipients)

        # Update brief_run sent_at if any were sent (with atomic race condition protection)
        if result['sent'] > 0:
            _mark_brief_run_sent(brief_run, reason=f"sent to {result['sent']} recipients")

        logger.info(
            f"Sent BriefRun {brief_run.id} to {result['sent']}/{total_recipients} recipients "
            f"({result['failed']} failed) via {result.get('method', 'unknown')}"
        )

        return result

    def _send_individual_to_recipients(
        self,
        brief_run: BriefRun,
        recipients: List[BriefRecipient]
    ) -> dict:
        """
        Send emails individually (for small lists or fallback).

        Args:
            brief_run: BriefRun instance
            recipients: List of recipients

        Returns:
            dict: {'sent': count, 'failed': count, 'method': 'individual'}
        """
        sent = 0
        failed = 0

        for recipient in recipients:
            try:
                if self.send_brief_run(brief_run, recipient):
                    sent += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Error sending to {recipient.email}: {e}")
                failed += 1

        return {'sent': sent, 'failed': failed, 'method': 'individual'}

    def _send_batch_to_recipients(
        self,
        brief_run: BriefRun,
        recipients: List[BriefRecipient]
    ) -> dict:
        """
        Send emails in batches using Resend Batch API.

        Chunks recipients into batches of 100 (Resend limit) and sends efficiently.
        Falls back to individual sending if batch fails.

        Args:
            brief_run: BriefRun instance
            recipients: List of recipients

        Returns:
            dict: {'sent': count, 'failed': count, 'method': 'batch'}
        """
        briefing = brief_run.briefing
        from_email = self._get_from_email(briefing)
        from_name = briefing.from_name or briefing.name
        subject = self._generate_subject(brief_run, briefing)
        base_url = get_base_url()

        BATCH_SIZE = 100  # Resend limit
        total_sent = 0
        total_failed = 0

        # Process in batches
        for batch_start in range(0, len(recipients), BATCH_SIZE):
            batch_recipients = recipients[batch_start:batch_start + BATCH_SIZE]
            batch_emails = []

            for recipient in batch_recipients:
                try:
                    html_content = self._render_brief_run_email(brief_run, recipient, briefing)
                    unsubscribe_url = f"{base_url}/briefings/{briefing.id}/unsubscribe/{recipient.magic_token or ''}"

                    email_data = {
                        'from': f"{from_name} <{from_email}>",
                        'to': [recipient.email],
                        'subject': subject,
                        'html': html_content,
                        'headers': {
                            'List-Unsubscribe': f'<{unsubscribe_url}>',
                            'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
                        }
                    }
                    batch_emails.append(email_data)
                except Exception as e:
                    logger.error(f"Error preparing email for {recipient.email}: {e}")
                    total_failed += 1

            if batch_emails:
                try:
                    # Use base client's batch send method
                    batch_result = self.base_client._send_batch(batch_emails)
                    total_sent += batch_result.get('sent', 0)
                    total_failed += batch_result.get('failed', 0)

                    if batch_result.get('errors'):
                        for error in batch_result['errors']:
                            logger.warning(f"Batch error: {error}")

                    batch_num = (batch_start // BATCH_SIZE) + 1
                    total_batches = (len(recipients) + BATCH_SIZE - 1) // BATCH_SIZE
                    logger.info(
                        f"Batch {batch_num}/{total_batches}: "
                        f"sent {batch_result.get('sent', 0)}, failed {batch_result.get('failed', 0)}"
                    )

                except Exception as e:
                    logger.error(f"Batch send failed, falling back to individual: {e}")
                    # Fallback to individual sending for this batch
                    for recipient in batch_recipients:
                        try:
                            if self.send_brief_run(brief_run, recipient):
                                total_sent += 1
                            else:
                                total_failed += 1
                        except Exception as inner_e:
                            logger.error(f"Individual fallback failed for {recipient.email}: {inner_e}")
                            total_failed += 1

        return {'sent': total_sent, 'failed': total_failed, 'method': 'batch'}


def send_brief_run_emails(brief_run_id: int, skip_subscription_check: bool = False) -> dict:
    """
    Convenience function to send BriefRun emails.
    
    Args:
        brief_run_id: BriefRun ID
        skip_subscription_check: Skip subscription validation (for admin/testing only)
    
    Returns:
        dict: {'sent': count, 'failed': count}
    """
    from app.billing.service import get_active_subscription
    from app.models import User, CompanyProfile
    
    brief_run = BriefRun.query.get(brief_run_id)
    if not brief_run:
        logger.error(f"BriefRun {brief_run_id} not found")
        return {'sent': 0, 'failed': 0}
    
    if brief_run.status != 'approved':
        logger.warning(f"BriefRun {brief_run_id} is not approved (status: {brief_run.status}), skipping send")
        return {'sent': 0, 'failed': 0}
    
    # Check subscription status before sending (unless explicitly skipped for admin)
    if not skip_subscription_check:
        briefing = brief_run.briefing
        has_active_subscription = False
        
        if briefing.owner_type == 'user':
            user = User.query.get(briefing.owner_id)
            if user:
                # Admin users always have access
                if user.is_admin:
                    has_active_subscription = True
                else:
                    sub = get_active_subscription(user)
                    has_active_subscription = sub is not None
        elif briefing.owner_type == 'org':
            # Check if organization has active subscription
            from app.models import Subscription
            sub = Subscription.query.filter(
                Subscription.org_id == briefing.owner_id,
                Subscription.status.in_(['trialing', 'active'])
            ).first()
            has_active_subscription = sub is not None
        
        if not has_active_subscription:
            logger.warning(
                f"Skipping send for BriefRun {brief_run_id} - owner has no active subscription "
                f"(owner_type={briefing.owner_type}, owner_id={briefing.owner_id})"
            )
            return {'sent': 0, 'failed': 0, 'skipped_reason': 'no_active_subscription'}
    
    client = BriefingEmailClient()
    return client.send_brief_run_to_all_recipients(brief_run)
