"""
Async Extraction Queue

Background job processor for PDF/DOCX text extraction.
Prevents blocking upload requests.
"""

import logging
from datetime import timedelta

from app.lib.time import utcnow_naive
from app import db
from app.models import InputSource
from app.briefing.ingestion import extract_text_from_pdf, extract_text_from_docx
from app.db_retry import discard_db_session, with_db_retry
from app.lib.db_transient_errors import is_transient_db_connectivity_error

logger = logging.getLogger(__name__)

# Timeout for stuck extractions (minutes)
EXTRACTION_TIMEOUT_MINUTES = 30


@with_db_retry()
def process_extraction_queue():
    """
    Process pending extraction jobs for InputSource uploads.

    Finds all InputSource instances with status='extracting' and processes them.
    Updates status to 'ready' on success or 'failed' on error.

    Also handles stuck extractions by timing out items that have been
    extracting for more than EXTRACTION_TIMEOUT_MINUTES.

    This should be called by APScheduler as a periodic job (e.g., every 10 seconds).
    Transient Neon/pooler disconnects are retried via ``with_db_retry``.
    """
    # First, timeout any stuck extractions
    timeout_stuck_extractions()

    # Find sources waiting for extraction
    pending_sources = InputSource.query.filter_by(
        status='extracting',
        type='upload'
    ).limit(10).all()  # Process 10 at a time to avoid overload

    if not pending_sources:
        return

    logger.info(f"Processing {len(pending_sources)} extraction jobs")

    for source in pending_sources:
        try:
            if not source.storage_key:
                logger.warning(f"InputSource {source.id} has no storage_key, skipping")
                source.status = 'failed'
                source.extraction_error = 'No storage key found'
                db.session.commit()
                continue

            # Determine file type and extract
            extracted_text = None
            if source.storage_key.lower().endswith('.pdf'):
                extracted_text = extract_text_from_pdf(source.storage_key)
            elif source.storage_key.lower().endswith(('.docx', '.doc')):
                extracted_text = extract_text_from_docx(source.storage_key)
            else:
                logger.warning(f"Unknown file type for {source.storage_key}")
                source.status = 'failed'
                source.extraction_error = f'Unknown file type: {source.storage_key}'
                db.session.commit()
                continue

            if extracted_text:
                source.extracted_text = extracted_text
                source.status = 'ready'
                source.extraction_error = None
                logger.info(
                    f"Successfully extracted text from {source.storage_key} "
                    f"({len(extracted_text)} chars)"
                )
            else:
                source.status = 'failed'
                source.extraction_error = 'Extraction returned no text'
                logger.warning(f"Extraction failed for {source.storage_key}")

            db.session.commit()

        except Exception as e:
            # Classify by message (same source of truth as with_db_retry), not by
            # exception type. A pooler blip must never mark the upload failed —
            # bubble so the decorated tick retries on a fresh connection when the
            # decorator recognises the type; otherwise leave status 'extracting'
            # for the next scheduler tick.
            if is_transient_db_connectivity_error(e):
                raise
            _record_extraction_failure(source, e)


def _record_extraction_failure(source, error) -> None:
    """Mark a source failed after a permanent error, surviving a poisoned session.

    Rolls back first so a status-only write can commit even when the error aborted
    the current transaction. If that write itself hits a connectivity drop, discard
    the session (invalidating the socket on transient errors) and leave the source
    'extracting' for the next tick to retry or time out — never a silent loss.
    """
    logger.error(
        f"Error processing extraction for InputSource {source.id}: {error}",
        exc_info=True,
    )
    try:
        db.session.rollback()
        source.status = 'failed'
        source.extraction_error = str(error)[:500]  # Truncate long errors
        db.session.commit()
    except Exception as commit_exc:
        discard_db_session(
            invalidate_connection=is_transient_db_connectivity_error(commit_exc),
        )


def timeout_stuck_extractions():
    """
    Mark stuck extractions as failed.

    An extraction is considered stuck if:
    - status is 'extracting'
    - updated_at is more than EXTRACTION_TIMEOUT_MINUTES ago

    This prevents items from being stuck in 'extracting' forever if
    the extraction process crashes or hangs.

    Retry is owned by the caller: this runs inside ``process_extraction_queue``
    (itself ``@with_db_retry``), so a transient Neon/pooler disconnect here
    bubbles up and retries the whole tick on a fresh connection. Decorating it
    again would nest retry loops (attempts multiply, blocking ``time.sleep``).
    """
    timeout_threshold = utcnow_naive() - timedelta(minutes=EXTRACTION_TIMEOUT_MINUTES)

    stuck_sources = InputSource.query.filter(
        InputSource.status == 'extracting',
        InputSource.type == 'upload',
        InputSource.updated_at < timeout_threshold
    ).all()

    if not stuck_sources:
        return

    logger.warning(f"Timing out {len(stuck_sources)} stuck extraction jobs")

    for source in stuck_sources:
        source.status = 'failed'
        source.extraction_error = (
            f'Extraction timed out after {EXTRACTION_TIMEOUT_MINUTES} minutes. '
            f'Please try uploading again.'
        )
        logger.warning(f"Timed out extraction for InputSource {source.id} ({source.name})")

    db.session.commit()


def retry_failed_extraction(source_id: int) -> bool:
    """
    Retry a failed extraction by resetting status to 'extracting'.

    Args:
        source_id: InputSource ID to retry

    Returns:
        bool: True if reset successful, False otherwise
    """
    try:
        source = db.session.get(InputSource, source_id)
        if not source:
            logger.error(f"InputSource {source_id} not found")
            return False

        if source.type != 'upload':
            logger.error(f"InputSource {source_id} is not an upload type")
            return False

        if source.status != 'failed':
            logger.warning(
                f"InputSource {source_id} is not in failed state (current: {source.status})"
            )
            return False

        source.status = 'extracting'
        source.extraction_error = None
        db.session.commit()

        logger.info(f"Reset InputSource {source_id} for retry")
        return True

    except Exception as e:
        logger.error(f"Error retrying extraction for InputSource {source_id}: {e}")
        discard_db_session(
            invalidate_connection=is_transient_db_connectivity_error(e),
        )
        return False
