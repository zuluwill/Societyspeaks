"""
Background job system for brief generation.

Uses Redis for job queuing and status tracking.
Jobs are processed by the scheduler which runs in the background.
"""

import os
import json
import logging
import threading
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import redis

logger = logging.getLogger(__name__)

REDIS_URL = os.environ.get('REDIS_URL')
JOB_PREFIX = 'briefing:job:'
JOB_EXPIRY = 3600  # Jobs expire after 1 hour


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
    - failed: Job failed with an error
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
            'progress_message': self.progress_message
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
        return job
    
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
    
    def update_status(self, status: str, message: str = '', brief_run_id: int = None, error: str = None):
        """Update job status and save."""
        self.status = status
        if message:
            self.progress_message = message
        if brief_run_id:
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
        Job ID if successful, None if failed
    """
    import uuid
    
    # Use full UUID for security (prevents guessing)
    job_id = str(uuid.uuid4())
    job = GenerationJob(job_id, briefing_id, user_id)
    
    client = get_redis_client()
    if not client:
        logger.warning("Redis not available - cannot queue async job")
        return None
    
    if job.save():
        try:
            client.lpush('briefing:generation_queue', job_id)
            logger.info(f"Queued generation job {job_id} for briefing {briefing_id}")
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
    Uses atomic status transition to prevent double-processing.
    """
    from app import db
    from app.models import Briefing, BriefRun
    from app.briefing.generator import BriefingGenerator
    import random
    
    job = GenerationJob.get(job_id)
    if not job:
        logger.error(f"Job {job_id} not found")
        return False
    
    # Atomic claim: only process if still queued
    if job.status != 'queued':
        logger.info(f"Job {job_id} already being processed (status: {job.status})")
        return False
    
    # Try to atomically claim the job
    client = get_redis_client()
    if client:
        lock_key = f"{JOB_PREFIX}{job_id}:lock"
        # Use SETNX for atomic claim - only one worker can get the lock
        if not client.setnx(lock_key, "1"):
            logger.info(f"Job {job_id} already claimed by another worker")
            return False
        # Set lock expiry to prevent deadlocks
        client.expire(lock_key, 300)  # 5 minute lock timeout
    
    try:
        job.update_status('processing', 'Loading briefing configuration...')
        
        briefing = Briefing.query.get(job.briefing_id)
        if not briefing:
            job.update_status('failed', error='Briefing not found')
            return False
        
        if not briefing.sources:
            job.update_status('failed', error='No sources configured for this briefing')
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
            job.update_status('failed', error='No content available from your sources. Try adding more sources or wait for content to be ingested.')
            return False
        
        brief_run.status = 'generated_draft'
        db.session.commit()
        
        job.update_status('completed', 'Brief generated successfully!', brief_run_id=brief_run.id)
        logger.info(f"Completed generation job {job_id} with brief_run {brief_run.id}")
        return True
        
    except Exception as e:
        logger.error(f"Error processing job {job_id}: {e}", exc_info=True)
        db.session.rollback()
        job.update_status('failed', error=str(e))
        return False


def get_next_job() -> Optional[str]:
    """Get next job from queue."""
    client = get_redis_client()
    if not client:
        return None
    
    try:
        job_id = client.rpop('briefing:generation_queue')
        return job_id
    except Exception as e:
        logger.error(f"Failed to get next job: {e}")
        return None


def process_pending_jobs():
    """
    Process all pending generation jobs.
    Called by the scheduler every few seconds.
    """
    from flask import current_app
    
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
