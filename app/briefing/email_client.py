"""
Briefing Email Client

Extends ResendClient for sending BriefRun emails to recipients.
Reuses existing email infrastructure with briefing-specific logic.
"""

import os
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from flask import render_template, current_app
from sqlalchemy import update
from app import db
from app.models import BriefRun, BriefRecipient, Briefing, SendingDomain, BriefEmailSend
from app.resend_client import ResendEmailClient as BaseResendClient
from app.storage_utils import get_base_url

logger = logging.getLogger(__name__)


def _claim_brief_run_for_sending(brief_run: BriefRun) -> bool:
    """
    Atomically claim a BriefRun for sending using UPDATE with WHERE clause.
    
    This MUST be called BEFORE sending starts to prevent race conditions
    where multiple scheduler jobs try to send the same brief.

    Args:
        brief_run: BriefRun instance to claim

    Returns:
        True if this process successfully claimed it for sending,
        False if another process already claimed it or it was already sent
    """
    from sqlalchemy import text
    
    try:
        # Atomically:
        # 1. Change status from 'approved' to 'sending'
        # 2. Set claimed_at to now (for recovery mechanism)
        # 3. Increment send_attempts (for monitoring/debugging)
        # This prevents other processes from picking up the same brief_run
        result = db.session.execute(
            update(BriefRun)
            .where(BriefRun.id == brief_run.id)
            .where(BriefRun.status == 'approved')  # Only claim if still approved
            .where(BriefRun.sent_at == None)  # Extra safety: only if not already sent
            .values(
                status='sending',
                claimed_at=datetime.utcnow(),
                send_attempts=BriefRun.send_attempts + 1
            )
        )
        db.session.commit()

        if result.rowcount == 0:
            # Another process already claimed it or it's no longer approved
            db.session.refresh(brief_run)
            logger.warning(
                f"BriefRun {brief_run.id} could not be claimed for sending "
                f"(current status: {brief_run.status}, sent_at: {brief_run.sent_at}). "
                f"Another process may be handling it."
            )
            return False

        logger.info(
            f"Claimed BriefRun {brief_run.id} for sending "
            f"(status -> 'sending', attempt #{brief_run.send_attempts + 1})"
        )
        return True

    except Exception as e:
        db.session.rollback()
        logger.error(f"Error claiming BriefRun {brief_run.id}: {e}", exc_info=True)
        return False


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
        # Accept either 'approved' or 'sending' status (for backward compatibility and new flow)
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
        all_eligible_recipients = briefing.recipients.filter(
            BriefRecipient.status == 'active',
            BriefRecipient.created_at <= run_timestamp
        ).all()

        # Filter out recipients who have already been sent this brief_run
        # Only filter out 'sent' status - 'claimed' status older than 10 minutes
        # should be treated as stale (crashed process) and can be retried
        stale_cutoff = datetime.utcnow() - timedelta(minutes=10)
        
        # Clean up stale claims FIRST (claimed > 10 minutes ago) to allow retry
        # This handles cases where a process crashed after send but before marking sent
        # Also clean up any 'failed' status entries so they can be retried
        cleanup_result = db.session.execute(
            db.text("""
                DELETE FROM brief_email_send 
                WHERE brief_run_id = :brief_run_id 
                AND (
                    (status = 'claimed' AND claimed_at < :stale_cutoff)
                    OR status = 'failed'
                )
            """),
            {'brief_run_id': brief_run.id, 'stale_cutoff': stale_cutoff}
        )
        if cleanup_result.rowcount > 0:
            logger.info(f"Cleaned up {cleanup_result.rowcount} stale/failed claim(s) for BriefRun {brief_run.id}")
        db.session.commit()
        
        # Now get recipients that are definitively sent or actively being processed
        # 'sent' status = definitely delivered, exclude
        # 'claimed' status with recent claimed_at = currently in progress, exclude
        already_handled = BriefEmailSend.query.filter(
            BriefEmailSend.brief_run_id == brief_run.id,
            db.or_(
                BriefEmailSend.status == 'sent',
                db.and_(
                    BriefEmailSend.status == 'claimed',
                    BriefEmailSend.claimed_at > stale_cutoff  # Recently claimed, in progress
                )
            )
        ).all()
        already_sent_recipient_ids = set(send.recipient_id for send in already_handled)
        recipients = [
            r for r in all_eligible_recipients 
            if r.id not in already_sent_recipient_ids
        ]
        
        already_sent_count = len(already_sent_recipient_ids)
        total_recipients = len(recipients)
        
        if already_sent_count > 0:
            logger.info(
                f"BriefRun {brief_run.id}: {already_sent_count} recipients already sent, "
                f"{total_recipients} remaining to send"
            )
        
        # Handle case where no eligible recipients remain
        # (either all added after run, or all already sent)
        if total_recipients == 0:
            # Count recipients with 'sent' status to distinguish "all sent" vs "still in progress"
            sent_count = BriefEmailSend.query.filter(
                BriefEmailSend.brief_run_id == brief_run.id,
                BriefEmailSend.status == 'sent'
            ).count()
            
            # Count recipients with active 'claimed' status (in progress by another process)
            claimed_count = BriefEmailSend.query.filter(
                BriefEmailSend.brief_run_id == brief_run.id,
                BriefEmailSend.status == 'claimed',
                BriefEmailSend.claimed_at > stale_cutoff
            ).count()
            
            if claimed_count > 0:
                # Still in progress by another process, don't mark as sent yet
                logger.info(
                    f"BriefRun {brief_run.id}: {claimed_count} recipients still being processed, "
                    f"waiting for completion"
                )
                return {
                    'sent': 0, 'failed': 0, 'method': 'none',
                    'skipped': 'in_progress_by_other_process',
                    'already_sent': sent_count,
                    'in_progress': claimed_count
                }
            
            reason = "no recipients remaining"
            if sent_count > 0:
                reason = f"all {sent_count} recipients already sent"
            elif len(all_eligible_recipients) == 0:
                reason = "no eligible recipients - all recipients added after run was created"
                
            _mark_brief_run_sent(brief_run, reason=reason)
            return {
                'sent': 0, 'failed': 0, 'method': 'none', 
                'skipped': 'no_remaining_recipients', 
                'already_sent': sent_count
            }

        # Use individual sending for reliable per-recipient tracking
        # This ensures each recipient is claimed before send and marked after,
        # preventing duplicates even with partial failures or process crashes.
        # The claim-before-send pattern doesn't work well with batch APIs
        # that don't provide per-recipient success/failure status.
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
        
        Uses claim-before-send pattern:
        1. Claim recipient atomically (prevents duplicates even if we crash)
        2. Send email
        3. Mark as sent (or remove claim on failure for retry)

        Args:
            brief_run: BriefRun instance
            recipients: List of recipients

        Returns:
            dict: {'sent': count, 'failed': count, 'method': 'individual'}
        """
        sent = 0
        failed = 0
        skipped = 0

        for recipient in recipients:
            # Step 1: Claim recipient BEFORE sending
            if not self._claim_recipient_for_send(brief_run.id, recipient.id):
                # Already claimed/sent by another process
                skipped += 1
                continue
            
            try:
                # Step 2: Send email
                if self.send_brief_run(brief_run, recipient):
                    # Step 3a: Mark as sent
                    self._mark_recipient_sent(brief_run.id, recipient.id)
                    sent += 1
                else:
                    # Step 3b: Send failed, remove claim for retry
                    self._mark_recipient_failed(brief_run.id, recipient.id)
                    failed += 1
            except Exception as e:
                logger.error(f"Error sending to {recipient.email}: {e}")
                # Remove claim on exception for retry
                self._mark_recipient_failed(brief_run.id, recipient.id)
                failed += 1

        if skipped > 0:
            logger.info(f"Skipped {skipped} already-claimed recipients")
            
        return {'sent': sent, 'failed': failed, 'skipped': skipped, 'method': 'individual'}
    
    def _claim_recipient_for_send(
        self, 
        brief_run_id: int, 
        recipient_id: int
    ) -> bool:
        """
        Claim a recipient BEFORE sending to prevent duplicates.
        
        Uses INSERT with ON CONFLICT DO NOTHING for atomicity.
        If insert succeeds, this process owns the send.
        If insert fails (conflict), another process already claimed it.
        
        Returns:
            True if claim succeeded (proceed with send)
            False if already claimed/sent (skip this recipient)
        """
        try:
            result = db.session.execute(
                db.text("""
                    INSERT INTO brief_email_send (brief_run_id, recipient_id, status, claimed_at)
                    VALUES (:brief_run_id, :recipient_id, 'claimed', NOW())
                    ON CONFLICT (brief_run_id, recipient_id) DO NOTHING
                """),
                {
                    'brief_run_id': brief_run_id,
                    'recipient_id': recipient_id
                }
            )
            db.session.commit()
            # If rowcount is 0, the recipient was already claimed/sent
            return result.rowcount > 0
        except Exception as e:
            logger.warning(f"Error claiming recipient {recipient_id}: {e}")
            db.session.rollback()
            return False
    
    def _mark_recipient_sent(
        self, 
        brief_run_id: int, 
        recipient_id: int, 
        resend_id: str = None
    ) -> bool:
        """
        Mark a claimed recipient as successfully sent.
        
        Called AFTER successful email delivery.
        """
        try:
            db.session.execute(
                db.text("""
                    UPDATE brief_email_send 
                    SET status = 'sent', resend_id = :resend_id, sent_at = NOW()
                    WHERE brief_run_id = :brief_run_id 
                    AND recipient_id = :recipient_id
                    AND status = 'claimed'
                """),
                {
                    'brief_run_id': brief_run_id,
                    'recipient_id': recipient_id,
                    'resend_id': resend_id
                }
            )
            db.session.commit()
            return True
        except Exception as e:
            logger.warning(f"Error marking recipient sent: {e}")
            db.session.rollback()
            return False
    
    def _mark_recipient_failed(
        self, 
        brief_run_id: int, 
        recipient_id: int
    ) -> bool:
        """
        Mark a claimed recipient as failed (so it can be retried).
        
        Deletes the claim record so the recipient can be retried.
        """
        try:
            db.session.execute(
                db.text("""
                    DELETE FROM brief_email_send 
                    WHERE brief_run_id = :brief_run_id 
                    AND recipient_id = :recipient_id
                    AND status = 'claimed'
                """),
                {
                    'brief_run_id': brief_run_id,
                    'recipient_id': recipient_id
                }
            )
            db.session.commit()
            return True
        except Exception as e:
            logger.warning(f"Error marking recipient failed: {e}")
            db.session.rollback()
            return False

    def _send_batch_to_recipients(
        self,
        brief_run: BriefRun,
        recipients: List[BriefRecipient]
    ) -> dict:
        """
        Send emails in batches using Resend Batch API.

        Uses claim-before-send pattern for each recipient to prevent duplicates.
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
        total_skipped = 0

        # Process in batches
        for batch_start in range(0, len(recipients), BATCH_SIZE):
            batch_recipients = recipients[batch_start:batch_start + BATCH_SIZE]
            
            # Step 1: Claim all recipients in batch BEFORE preparing emails
            claimed_recipients = []
            for recipient in batch_recipients:
                if self._claim_recipient_for_send(brief_run.id, recipient.id):
                    claimed_recipients.append(recipient)
                else:
                    total_skipped += 1
            
            if not claimed_recipients:
                continue
            
            batch_emails = []
            # Map email index to recipient for tracking
            email_to_recipient = []

            for recipient in claimed_recipients:
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
                    email_to_recipient.append(recipient)
                except Exception as e:
                    logger.error(f"Error preparing email for {recipient.email}: {e}")
                    # Remove claim for retry
                    self._mark_recipient_failed(brief_run.id, recipient.id)
                    total_failed += 1

            if batch_emails:
                try:
                    # Use base client's batch send method
                    batch_result = self.base_client._send_batch(batch_emails)
                    batch_sent = batch_result.get('sent', 0)
                    batch_failed = batch_result.get('failed', 0)
                    total_sent += batch_sent
                    total_failed += batch_failed

                    if batch_result.get('errors'):
                        for error in batch_result['errors']:
                            logger.warning(f"Batch error: {error}")
                    
                    # Step 2: Mark all recipients in this batch as sent
                    # Note: Batch API sends all or fails all, so we mark all as sent
                    if batch_sent > 0:
                        for recipient in email_to_recipient:
                            self._mark_recipient_sent(brief_run.id, recipient.id)
                    else:
                        # Batch failed completely - remove claims for retry
                        for recipient in email_to_recipient:
                            self._mark_recipient_failed(brief_run.id, recipient.id)

                    batch_num = (batch_start // BATCH_SIZE) + 1
                    total_batches = (len(recipients) + BATCH_SIZE - 1) // BATCH_SIZE
                    logger.info(
                        f"Batch {batch_num}/{total_batches}: "
                        f"sent {batch_sent}, failed {batch_failed}"
                    )

                except Exception as e:
                    logger.error(f"Batch send failed, falling back to individual: {e}")
                    # Remove claims and fallback to individual sending for claimed recipients
                    for recipient in email_to_recipient:
                        self._mark_recipient_failed(brief_run.id, recipient.id)
                    
                    # Fallback to individual sending (will re-claim)
                    fallback_result = self._send_individual_to_recipients(brief_run, claimed_recipients)
                    total_sent += fallback_result.get('sent', 0)
                    total_failed += fallback_result.get('failed', 0)

        if total_skipped > 0:
            logger.info(f"Batch sending skipped {total_skipped} already-claimed recipients")
            
        return {'sent': total_sent, 'failed': total_failed, 'skipped': total_skipped, 'method': 'batch'}


def send_brief_run_emails(brief_run_id: int, skip_subscription_check: bool = False) -> dict:
    """
    Convenience function to send BriefRun emails.
    
    Uses atomic claim mechanism to prevent duplicate sends from concurrent processes.
    
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
    
    # Check status - must be 'approved' to send
    # 'sending' means another process already claimed it (treat as already in progress)
    # 'sent' means it's already been sent
    if brief_run.status == 'sending':
        logger.info(f"BriefRun {brief_run_id} is already being sent by another process, skipping")
        return {'sent': 0, 'failed': 0, 'skipped_reason': 'already_sending'}
    
    if brief_run.status != 'approved':
        logger.warning(f"BriefRun {brief_run_id} is not approved (status: {brief_run.status}), skipping")
        return {'sent': 0, 'failed': 0}
    
    # Atomically claim the brief_run for sending BEFORE we start
    # This prevents race conditions where multiple scheduler jobs try to send
    if not _claim_brief_run_for_sending(brief_run):
        logger.info(f"BriefRun {brief_run_id} already claimed by another process, skipping")
        return {'sent': 0, 'failed': 0, 'skipped_reason': 'already_claimed'}
    
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
            # Reset status back to approved so it doesn't get stuck in 'sending'
            db.session.execute(
                update(BriefRun)
                .where(BriefRun.id == brief_run_id)
                .where(BriefRun.status == 'sending')
                .values(status='approved')
            )
            db.session.commit()
            return {'sent': 0, 'failed': 0, 'skipped_reason': 'no_active_subscription'}
    
    try:
        client = BriefingEmailClient()
        return client.send_brief_run_to_all_recipients(brief_run)
    except Exception as e:
        # If sending fails completely, reset status to approved for retry
        logger.error(f"Error sending BriefRun {brief_run_id}: {e}", exc_info=True)
        db.session.execute(
            update(BriefRun)
            .where(BriefRun.id == brief_run_id)
            .where(BriefRun.status == 'sending')
            .values(status='approved')
        )
        db.session.commit()
        raise
