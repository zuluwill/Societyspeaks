"""
Queued ingestion jobs for briefing source ingestion.

Adds queueing/backpressure controls so source ingestion can scale without
unbounded inline loops in scheduler cycles.
"""

import json
import os
import logging
from typing import Optional

from app import db
from app.models import InputSource
from app.briefing.ingestion.source_ingester import SourceIngester


logger = logging.getLogger(__name__)

INGESTION_QUEUE_KEY = 'briefing:ingestion_queue'
INGESTION_QUEUE_MAX_SIZE = int(os.environ.get('BRIEFING_INGESTION_QUEUE_MAX_SIZE', '5000'))
INGESTION_DEDUPE_TTL_SECONDS = int(os.environ.get('BRIEFING_INGESTION_DEDUPE_TTL_SECONDS', '60'))


def _get_redis_client():
    from app.lib.redis_client import get_client
    return get_client(decode_responses=True)


def queue_ingestion_job(
    source_id: int,
    days_back: int = 7,
    reason: Optional[str] = None
) -> bool:
    """
    Queue a source ingestion job with dedupe and backpressure.

    Falls back to immediate synchronous ingestion when Redis is unavailable.
    """
    source = db.session.get(InputSource, source_id)
    if not source or not source.enabled:
        return False

    payload = {
        'source_id': source_id,
        'days_back': days_back,
        'reason': reason or 'scheduled'
    }

    client = _get_redis_client()
    if not client:
        # Graceful fallback: keep current behavior if queue infra is unavailable.
        try:
            SourceIngester().ingest_source(source, days_back=days_back)
            return True
        except Exception as e:
            logger.error(f"Synchronous ingestion fallback failed for source {source_id}: {e}")
            db.session.rollback()
            return False

    dedupe_key = f"briefing:ingestion:dedupe:{source_id}"
    try:
        if not client.set(dedupe_key, "1", nx=True, ex=INGESTION_DEDUPE_TTL_SECONDS):
            return True

        queue_size = client.llen(INGESTION_QUEUE_KEY)
        if queue_size >= INGESTION_QUEUE_MAX_SIZE:
            logger.warning(
                f"Ingestion queue full ({queue_size}/{INGESTION_QUEUE_MAX_SIZE}); dropping source {source_id}"
            )
            return False

        client.lpush(INGESTION_QUEUE_KEY, json.dumps(payload))
        return True
    except Exception as e:
        logger.error(f"Failed to queue ingestion job for source {source_id}: {e}")
        return False


def process_pending_ingestion_jobs(max_jobs: int = 20) -> int:
    """
    Process queued ingestion jobs.

    Returns number of jobs processed this cycle.
    """
    client = _get_redis_client()
    if not client:
        return 0

    processed = 0
    ingester = SourceIngester()
    while processed < max_jobs:
        try:
            raw = client.rpop(INGESTION_QUEUE_KEY)
            if not raw:
                break
            payload = json.loads(raw)
            source_id = int(payload.get('source_id'))
            days_back = int(payload.get('days_back', 7))
        except Exception as e:
            logger.error(f"Failed to read ingestion job payload: {e}")
            continue

        source = db.session.get(InputSource, source_id)
        if not source or not source.enabled:
            processed += 1
            continue

        try:
            ingester.ingest_source(source, days_back=days_back)
        except Exception as e:
            logger.error(f"Error ingesting queued source {source_id}: {e}")
            db.session.rollback()
        finally:
            processed += 1

    if processed > 0:
        logger.info(f"Processed {processed} queued source-ingestion jobs")
    return processed
