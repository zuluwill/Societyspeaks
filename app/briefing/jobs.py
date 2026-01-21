"""
Background job system for brief generation.

Uses Redis for job queuing and status tracking.
Jobs are processed by the scheduler which runs in the background.

Features:
- Automatic retry with exponential backoff
- Dead-letter queue for permanently failed jobs
- Queue size limits to prevent runaway growth
- Metrics logging for monitoring
"""

import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get('REDIS_URL')
JOB_PREFIX = 'briefing:job:'
JOB_EXPIRY = 3600  # Jobs expire after 1 hour

# Retry configuration
MAX_RETRIES = 3  # Maximum retry attempts
RETRY_BACKOFF_BASE = 30  # Base delay in seconds (30s, 60s, 120s)
RETRY_BACKOFF_MULTIPLIER = 2  # Exponential multiplier

# Queue limits
MAX_QUEUE_SIZE = 1000  # Maximum pending jobs in queue
DEAD_LETTER_QUEUE = 'briefing:dead_letter_queue'
RETRY_QUEUE = 'briefing:retry_queue'


def get_redis_client():
    """Get Redis client connection."""
    if not REDIS_URL:
        return None
    try:
        return redis.from_url(REDIS_URL, decode_responses=True)
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        return None


class GenerationJob:
    """
    Represents a brief generation job.

    Statuses:
    - queued: Job is waiting to be processed
    - processing: Job is being worked on
    - completed: Job finished successfully
    - failed: Job failed with an error (may be retried)
    - dead: Job permanently failed after max retries
    """

    def __init__(self, job_id: str, briefing_id: int, user_id: int):
        self.job_id = job_id
        self.briefing_id = briefing_id
        self.user_id = user_id
        self.status = 'queued'
        self.brief_run_id: Optional[int] = None
        self.error: Optional[str] = None
        self.created_at = datetime.utcnow().isoformat()
        self.updated_at = datetime.utcnow().isoformat()
        self.progress_message = 'Preparing to generate brief...'
        # Retry tracking
        self.retry_count = 0
        self.next_retry_at: Optional[str] = None
        self.error_history: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            'job_id': self.job_id,
            'briefing_id': self.briefing_id,
            'user_id': self.user_id,
            'status': self.status,
            'brief_run_id': self.brief_run_id,
            'error': self.error,
            'created_at': self.created_at,
            'updated_at': self.updated_at,
            'progress_message': self.progress_message,
            'retry_count': self.retry_count,
            'next_retry_at': self.next_retry_at,
            'error_history': self.error_history
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'GenerationJob':
        job = cls(
            job_id=data['job_id'],
            briefing_id=data['briefing_id'],
            user_id=data['user_id']
        )
        job.status = data.get('status', 'queued')
        job.brief_run_id = data.get('brief_run_id')
        job.error = data.get('error')
        job.created_at = data.get('created_at', datetime.utcnow().isoformat())
        job.updated_at = data.get('updated_at', datetime.utcnow().isoformat())
        job.progress_message = data.get('progress_message', '')
        job.retry_count = data.get('retry_count', 0)
        job.next_retry_at = data.get('next_retry_at')
        job.error_history = data.get('error_history', [])
        return job

    def calculate_retry_delay(self) -> int:
        """Calculate delay before next retry using exponential backoff."""
        return RETRY_BACKOFF_BASE * (RETRY_BACKOFF_MULTIPLIER ** self.retry_count)

    def can_retry(self) -> bool:
        """Check if job can be retried."""
        return self.retry_count < MAX_RETRIES

    def schedule_retry(self, error_msg: str) -> bool:
        """
        Schedule job for retry with exponential backoff.

        Args:
            error_msg: Error message from the failure

        Returns:
            bool: True if retry scheduled, False if max retries exceeded
        """
        # Add error to history
        self.error_history.append(f"[{datetime.utcnow().isoformat()}] {error_msg}")
        self.error = error_msg

        if not self.can_retry():
            # Max retries exceeded - move to dead letter queue
            self.status = 'dead'
            self.progress_message = f'Permanently failed after {MAX_RETRIES} attempts'
            self.save()
            _move_to_dead_letter(self)
            logger.error(f"Job {self.job_id} moved to dead letter queue after {MAX_RETRIES} retries")
            return False

        # Calculate delay BEFORE incrementing retry_count for correct timing:
        # retry 1: 30s, retry 2: 60s, retry 3: 120s
        delay = self.calculate_retry_delay()
        self.retry_count += 1
        self.next_retry_at = (datetime.utcnow() + timedelta(seconds=delay)).isoformat()
        self.status = 'queued'  # Reset to queued for retry
        self.progress_message = f'Retry {self.retry_count}/{MAX_RETRIES} scheduled in {delay}s'
        self.save()

        # Add to retry queue with scheduled time
        _schedule_retry(self.job_id, delay)
        logger.info(f"Job {self.job_id} scheduled for retry {self.retry_count}/{MAX_RETRIES} in {delay}s")
        return True
    
    def save(self) -> bool:
        """Save job to Redis."""
        client = get_redis_client()
        if not client:
            return False
        
        try:
            self.updated_at = datetime.utcnow().isoformat()
            key = f"{JOB_PREFIX}{self.job_id}"
            client.setex(key, JOB_EXPIRY, json.dumps(self.to_dict()))
            return True
        except Exception as e:
            logger.error(f"Failed to save job {self.job_id}: {e}")
            return False
    
    @classmethod
    def get(cls, job_id: str) -> Optional['GenerationJob']:
        """Get job from Redis."""
        client = get_redis_client()
        if not client:
            return None
        
        try:
            key = f"{JOB_PREFIX}{job_id}"
            data = client.get(key)
            if data:
                return cls.from_dict(json.loads(data))
            return None
        except Exception as e:
            logger.error(f"Failed to get job {job_id}: {e}")
            return None
    
    def update_status(self, status: str, message: str = '', brief_run_id: Optional[int] = None, error: Optional[str] = None):
        """Update job status and save."""
        self.status = status
        if message:
            self.progress_message = message
        if brief_run_id is not None:  # Use explicit None check (ID could theoretically be 0)
            self.brief_run_id = brief_run_id
        if error:
            self.error = error
        self.save()


def queue_brief_generation(briefing_id: int, user_id: int) -> Optional[str]:
    """
    Queue a brief generation job.

    Args:
        briefing_id: ID of the briefing to generate
        user_id: ID of the user who triggered the generation

    Returns:
        Job ID if successful, None if failed (including when queue is full)
    """
    import uuid

    client = get_redis_client()
    if not client:
        logger.warning("Redis not available - cannot queue async job")
        return None

    # Check queue size limit to prevent runaway growth
    try:
        queue_size = client.llen('briefing:generation_queue')
        if queue_size >= MAX_QUEUE_SIZE:
            logger.warning(f"Queue full ({queue_size}/{MAX_QUEUE_SIZE}) - rejecting new job for briefing {briefing_id}")
            _log_metrics('queue_full_rejection', {'briefing_id': briefing_id, 'queue_size': queue_size})
            return None
    except Exception as e:
        logger.warning(f"Could not check queue size: {e}")
        # Continue anyway - better to accept job than reject due to check failure

    # Use full UUID for security (prevents guessing)
    job_id = str(uuid.uuid4())
    job = GenerationJob(job_id, briefing_id, user_id)

    if job.save():
        try:
            client.lpush('briefing:generation_queue', job_id)
            logger.info(f"Queued generation job {job_id} for briefing {briefing_id}")
            _log_metrics('job_queued', {'job_id': job_id, 'briefing_id': briefing_id})
            return job_id
        except Exception as e:
            logger.error(f"Failed to queue job: {e}")

    return None


def is_redis_available() -> bool:
    """Check if Redis is available for async processing."""
    client = get_redis_client()
    if not client:
        return False
    try:
        client.ping()
        return True
    except Exception:
        return False


def process_generation_job(job_id: str) -> bool:
    """
    Process a brief generation job.

    This is called by the background worker.
    Uses atomic lock acquisition to prevent double-processing.
    On failure, automatically schedules retry with exponential backoff.
    """
    from app import db
    from app.models import Briefing, BriefRun
    from app.briefing.generator import BriefingGenerator
    import random

    client = get_redis_client()
    lock_key = f"{JOB_PREFIX}{job_id}:lock"
    lock_acquired = False
    job = None  # Initialize for finally block

    try:
        # Try to atomically claim the job FIRST (before reading job state)
        # This prevents race conditions where status is checked before lock
        if client:
            # Use SETNX for atomic claim - only one worker can get the lock
            lock_acquired = client.setnx(lock_key, "1")
            if not lock_acquired:
                logger.info(f"Job {job_id} already claimed by another worker")
                return False
            # Set lock expiry to prevent deadlocks
            client.expire(lock_key, 300)  # 5 minute lock timeout

        # Now safely read job state (we hold the lock)
        job = GenerationJob.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return False

        # Check status AFTER acquiring lock to prevent race condition
        if job.status != 'queued':
            logger.info(f"Job {job_id} already being processed (status: {job.status})")
            return False

        job.update_status('processing', 'Loading briefing configuration...')
        _log_metrics('job_started', {'job_id': job_id, 'retry_count': job.retry_count})

        briefing = Briefing.query.get(job.briefing_id)
        if not briefing:
            # Non-retryable error - briefing doesn't exist
            job.update_status('failed', error='Briefing not found')
            _log_metrics('job_failed_permanent', {'job_id': job_id, 'reason': 'briefing_not_found'})
            return False

        if not briefing.sources:
            # Non-retryable error - no sources configured
            job.update_status('failed', error='No sources configured for this briefing')
            _log_metrics('job_failed_permanent', {'job_id': job_id, 'reason': 'no_sources'})
            return False

        job.update_status('processing', 'Selecting content from sources...')

        generator = BriefingGenerator()
        test_scheduled_at = datetime.utcnow() + timedelta(microseconds=random.randint(1, 999999))

        job.update_status('processing', 'Generating brief content with AI...')

        brief_run = generator.generate_brief_run(
            briefing=briefing,
            scheduled_at=test_scheduled_at,
            ingested_items=None
        )

        if brief_run is None:
            # Semi-retryable - might have content later
            error_msg = 'No content available from your sources. Try adding more sources or wait for content to be ingested.'
            job.update_status('failed', error=error_msg)
            _log_metrics('job_failed', {'job_id': job_id, 'reason': 'no_content'})
            return False

        brief_run.status = 'generated_draft'
        db.session.commit()

        job.update_status('completed', 'Brief generated successfully!', brief_run_id=brief_run.id)
        _log_metrics('job_completed', {'job_id': job_id, 'brief_run_id': brief_run.id})
        logger.info(f"Completed generation job {job_id} with brief_run {brief_run.id}")
        return True

    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
        db.session.rollback()

        # Schedule retry for transient errors
        try:
            if job is None:
                job = GenerationJob.get(job_id)
            if job:
                error_msg = str(e)
                if job.can_retry():
                    # Schedule retry with exponential backoff
                    job.schedule_retry(error_msg)
                    _log_metrics('job_retry_scheduled', {
                        'job_id': job_id,
                        'retry_count': job.retry_count,
                        'delay': job.calculate_retry_delay()
                    })
                else:
                    # Max retries exceeded
                    job.update_status('dead', error=error_msg)
                    _log_metrics('job_dead', {'job_id': job_id, 'error': error_msg})
        except Exception as update_error:
            logger.error(f"Failed to update job status: {update_error}")

        return False

    finally:
        # Always release the lock when done (explicit cleanup)
        if lock_acquired and client:
            try:
                client.delete(lock_key)
            except Exception as e:
                logger.warning(f"Failed to release lock for job {job_id}: {e}")


def get_next_job() -> Optional[str]:
    """Get next job from queue."""
    client = get_redis_client()
    if not client:
        return None
    
    try:
        job_id = client.rpop('briefing:generation_queue')
        return str(job_id) if job_id else None
    except Exception as e:
        logger.error(f"Failed to get next job: {e}")
        return None


def process_pending_jobs():
    """
    Process all pending generation jobs.
    Called by the scheduler every few seconds.
    Also processes any retry jobs that are due.
    """
    from flask import current_app

    # First, process retry queue (jobs scheduled for retry)
    _process_retry_queue()

    processed = 0
    max_jobs = 5  # Process up to 5 jobs per run

    while processed < max_jobs:
        job_id = get_next_job()
        if not job_id:
            break

        try:
            process_generation_job(job_id)
            processed += 1
        except Exception as e:
            logger.error(f"Error processing job {job_id}: {e}")

    if processed > 0:
        logger.info(f"Processed {processed} generation jobs")


# =============================================================================
# HELPER FUNCTIONS FOR RETRY AND DEAD LETTER QUEUE
# =============================================================================

def _schedule_retry(job_id: str, delay_seconds: int) -> bool:
    """
    Schedule a job for retry after a delay.

    Uses a sorted set with score = timestamp when retry should happen.

    Args:
        job_id: Job ID to retry
        delay_seconds: Delay before retry in seconds

    Returns:
        bool: True if scheduled successfully
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        retry_at = datetime.utcnow() + timedelta(seconds=delay_seconds)
        retry_timestamp = retry_at.timestamp()

        # Add to sorted set with score = retry timestamp
        client.zadd(RETRY_QUEUE, {job_id: retry_timestamp})
        logger.debug(f"Scheduled retry for job {job_id} at {retry_at.isoformat()}")
        return True
    except Exception as e:
        logger.error(f"Failed to schedule retry for job {job_id}: {e}")
        return False


def _process_retry_queue() -> int:
    """
    Process jobs from the retry queue that are due.

    Moves due retry jobs back to the main processing queue.

    Returns:
        int: Number of jobs moved to processing queue
    """
    client = get_redis_client()
    if not client:
        return 0

    try:
        now = datetime.utcnow().timestamp()
        # Get all jobs with retry time <= now
        due_jobs = client.zrangebyscore(RETRY_QUEUE, '-inf', now)

        if not due_jobs:
            return 0

        moved = 0
        for job_id in list(due_jobs):
            try:
                # Remove from retry queue
                client.zrem(RETRY_QUEUE, job_id)
                # Add back to main queue for processing
                client.lpush('briefing:generation_queue', job_id)
                moved += 1
                logger.info(f"Moved job {job_id} from retry queue to processing queue")
            except Exception as e:
                logger.error(f"Failed to move retry job {job_id}: {e}")

        if moved > 0:
            _log_metrics('retry_jobs_processed', {'count': moved})

        return moved
    except Exception as e:
        logger.error(f"Failed to process retry queue: {e}")
        return 0


def _move_to_dead_letter(job: 'GenerationJob') -> bool:
    """
    Move a permanently failed job to the dead letter queue.

    Args:
        job: GenerationJob instance

    Returns:
        bool: True if moved successfully
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        # Store job data in dead letter queue (list for easy inspection)
        dead_job_data = json.dumps({
            **job.to_dict(),
            'moved_to_dead_letter_at': datetime.utcnow().isoformat()
        })
        client.lpush(DEAD_LETTER_QUEUE, dead_job_data)

        # Keep dead letter queue from growing unbounded (max 1000 entries)
        client.ltrim(DEAD_LETTER_QUEUE, 0, 999)

        logger.info(f"Moved job {job.job_id} to dead letter queue")
        return True
    except Exception as e:
        logger.error(f"Failed to move job {job.job_id} to dead letter queue: {e}")
        return False


def _log_metrics(event: str, data: Dict[str, Any]) -> None:
    """
    Log metrics for monitoring.

    In production, this could send to a metrics service (Datadog, CloudWatch, etc.).
    For now, logs in a structured format that can be parsed.

    Args:
        event: Event name (e.g., 'job_completed', 'job_failed')
        data: Event data dictionary
    """
    try:
        metrics_data = {
            'event': event,
            'timestamp': datetime.utcnow().isoformat(),
            **data
        }
        # Log as JSON for easy parsing by log aggregation tools
        logger.info(f"METRICS: {json.dumps(metrics_data)}")
    except Exception as e:
        logger.warning(f"Failed to log metrics: {e}")


def get_queue_metrics() -> Dict[str, Any]:
    """
    Get current queue metrics for monitoring.

    Returns:
        dict: Queue metrics including sizes and job counts
    """
    client = get_redis_client()
    if not client:
        return {'error': 'Redis not available'}

    try:
        metrics = {
            'timestamp': datetime.utcnow().isoformat(),
            'main_queue_size': client.llen('briefing:generation_queue'),
            'retry_queue_size': client.zcard(RETRY_QUEUE),
            'dead_letter_queue_size': client.llen(DEAD_LETTER_QUEUE),
            'max_queue_size': MAX_QUEUE_SIZE,
            'queue_utilization_pct': 0
        }

        # Calculate utilization percentage
        if MAX_QUEUE_SIZE > 0:
            metrics['queue_utilization_pct'] = round(
                (metrics['main_queue_size'] / MAX_QUEUE_SIZE) * 100, 2
            )

        return metrics
    except Exception as e:
        logger.error(f"Failed to get queue metrics: {e}")
        return {'error': str(e)}


def get_dead_letter_jobs(limit: int = 50) -> List[Dict[str, Any]]:
    """
    Get jobs from the dead letter queue for inspection.

    Args:
        limit: Maximum number of jobs to return

    Returns:
        list: List of dead letter job data
    """
    client = get_redis_client()
    if not client:
        return []

    try:
        dead_jobs = client.lrange(DEAD_LETTER_QUEUE, 0, limit - 1)
        return [json.loads(job_data) for job_data in list(dead_jobs)]
    except Exception as e:
        logger.error(f"Failed to get dead letter jobs: {e}")
        return []


def retry_dead_letter_job(job_id: str) -> bool:
    """
    Manually retry a job from the dead letter queue.

    Resets the job's retry count and moves it back to the main queue.

    Args:
        job_id: Job ID to retry

    Returns:
        bool: True if successfully requeued
    """
    client = get_redis_client()
    if not client:
        return False

    try:
        job = GenerationJob.get(job_id)
        if not job:
            logger.error(f"Job {job_id} not found")
            return False

        # Reset retry state
        job.retry_count = 0
        job.status = 'queued'
        job.error = None
        job.next_retry_at = None
        job.progress_message = 'Manually requeued from dead letter'
        job.save()

        # Add back to main queue
        client.lpush('briefing:generation_queue', job_id)

        # Note: We don't remove from dead letter queue automatically
        # as we want to keep the history. Admin can clear it manually.

        logger.info(f"Manually requeued job {job_id} from dead letter queue")
        _log_metrics('dead_letter_retry', {'job_id': job_id})
        return True
    except Exception as e:
        logger.error(f"Failed to retry dead letter job {job_id}: {e}")
        return False
