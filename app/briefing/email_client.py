"""
Briefing Email Client

Extends ResendClient for sending BriefRun emails to recipients.
Reuses existing email infrastructure with briefing-specific logic.
"""

import os
import logging
from datetime import datetime
from typing import List, Optional
from flask import render_template, current_app
from app import db
from app.models import BriefRun, BriefRecipient, Briefing, SendingDomain
from app.brief.email_client import ResendClient as BaseResendClient

logger = logging.getLogger(__name__)


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
            base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL', 'https://societyspeaks.io')
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
        base_url = os.environ.get('APP_BASE_URL') or os.environ.get('SITE_URL', 'https://societyspeaks.io')
        base_url = base_url.rstrip('/')
        
        # Use approved content if available, otherwise draft
        content_html = brief_run.approved_html or brief_run.draft_html or ''
        content_markdown = brief_run.approved_markdown or brief_run.draft_markdown or ''
        
        # Build URLs
        view_url = f"{base_url}/briefings/{briefing.id}/runs/{brief_run.id}"
        unsubscribe_url = f"{base_url}/briefings/{briefing.id}/unsubscribe/{recipient.magic_token or ''}"
        
        # Get company logo if org briefing
        company_logo_url = None
        if briefing.owner_type == 'org' and briefing.owner_id:
            from app.models import CompanyProfile
            company = CompanyProfile.query.get(briefing.owner_id)
            if company and company.logo:
                # Build full URL for logo
                company_logo_url = f"{base_url}/profiles/image/{company.logo}"
        
        # Try to render template, fallback to simple HTML
        try:
            html = render_template(
                'emails/brief_run.html',
                brief_run=brief_run,
                briefing=briefing,
                recipient=recipient,
                content_html=content_html,
                view_url=view_url,
                unsubscribe_url=unsubscribe_url,
                base_url=base_url,
                company_logo_url=company_logo_url
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
        
        Args:
            brief_run: BriefRun instance
        
        Returns:
            dict: {'sent': count, 'failed': count}
        """
        briefing = brief_run.briefing
        recipients = briefing.recipients.filter_by(status='active').all()
        
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
        
        # Update brief_run sent_at if any were sent
        if sent > 0:
            brief_run.sent_at = datetime.utcnow()
            brief_run.status = 'sent'
            db.session.commit()
        
        logger.info(f"Sent BriefRun {brief_run.id} to {sent} recipients ({failed} failed)")
        
        return {'sent': sent, 'failed': failed}


def send_brief_run_emails(brief_run_id: int) -> dict:
    """
    Convenience function to send BriefRun emails.
    
    Args:
        brief_run_id: BriefRun ID
    
    Returns:
        dict: {'sent': count, 'failed': count}
    """
    brief_run = BriefRun.query.get(brief_run_id)
    if not brief_run:
        logger.error(f"BriefRun {brief_run_id} not found")
        return {'sent': 0, 'failed': 0}
    
    if brief_run.status != 'approved':
        logger.warning(f"BriefRun {brief_run_id} is not approved (status: {brief_run.status}), skipping send")
        return {'sent': 0, 'failed': 0}
    
    client = BriefingEmailClient()
    return client.send_brief_run_to_all_recipients(brief_run)
