"""
Async Extraction Queue

Background job processor for PDF/DOCX text extraction.
Prevents blocking upload requests.
"""

import logging
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive
from app import db
from app.models import InputSource
from app.briefing.ingestion import extract_text_from_pdf, extract_text_from_docx

logger = logging.getLogger(__name__)

# Timeout for stuck extractions (minutes)
EXTRACTION_TIMEOUT_MINUTES = 30


def process_extraction_queue():
    """
    Process pending extraction jobs for InputSource uploads.

    Finds all InputSource instances with status='extracting' and processes them.
    Updates status to 'ready' on success or 'failed' on error.

    Also handles stuck extractions by timing out items that have been
    extracting for more than EXTRACTION_TIMEOUT_MINUTES.

    This should be called by APScheduler as a periodic job (e.g., every 10 seconds).
    """
    try:
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
                    logger.info(f"Successfully extracted text from {source.storage_key} ({len(extracted_text)} chars)")
                else:
                    source.status = 'failed'
                    source.extraction_error = 'Extraction returned no text'
                    logger.warning(f"Extraction failed for {source.storage_key}")
                
                db.session.commit()
                
            except Exception as e:
                logger.error(f"Error processing extraction for InputSource {source.id}: {e}", exc_info=True)
                try:
                    source.status = 'failed'
                    source.extraction_error = str(e)[:500]  # Truncate long errors
                    db.session.commit()
                except:
                    db.session.rollback()
        
    except Exception as e:
        logger.error(f"Error in extraction queue processor: {e}", exc_info=True)
        db.session.rollback()


def timeout_stuck_extractions():
    """
    Mark stuck extractions as failed.

    An extraction is considered stuck if:
    - status is 'extracting'
    - updated_at is more than EXTRACTION_TIMEOUT_MINUTES ago

    This prevents items from being stuck in 'extracting' forever if
    the extraction process crashes or hangs.
    """
    try:
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
            source.extraction_error = f'Extraction timed out after {EXTRACTION_TIMEOUT_MINUTES} minutes. Please try uploading again.'
            logger.warning(f"Timed out extraction for InputSource {source.id} ({source.name})")

        db.session.commit()

    except Exception as e:
        logger.error(f"Error timing out stuck extractions: {e}", exc_info=True)
        db.session.rollback()


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
            logger.warning(f"InputSource {source_id} is not in failed state (current: {source.status})")
            return False

        source.status = 'extracting'
        source.extraction_error = None
        db.session.commit()

        logger.info(f"Reset InputSource {source_id} for retry")
        return True

    except Exception as e:
        logger.error(f"Error retrying extraction for InputSource {source_id}: {e}")
        db.session.rollback()
        return False
