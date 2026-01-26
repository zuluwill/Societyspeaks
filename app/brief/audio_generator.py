"""
Batch Audio Generation Service

Handles generating audio for all items in a daily brief.
Uses background jobs with progress tracking.

Optimized for Replit:
- Database-level locking to prevent race conditions
- Stale job recovery
- Failed item tracking
- Memory-conscious processing
"""

import logging
from typing import Optional
from datetime import datetime, timedelta
import hashlib
import os

from sqlalchemy.exc import IntegrityError

from app import db
from app.models import DailyBrief, BriefItem, AudioGenerationJob
from app.brief.xtts_client import XTTSClient
from app.brief.audio_storage import audio_storage

logger = logging.getLogger(__name__)

# Job timeout in minutes - jobs stuck longer than this are considered stale
JOB_TIMEOUT_MINUTES = 30


class AudioGenerator:
    """
    Service for batch audio generation.

    Generates audio for all items in a brief using XTTS v2,
    with progress tracking and error handling.
    """

    def __init__(self):
        self.xtts_client = XTTSClient()
        self.storage = audio_storage

    def create_generation_job(
        self,
        brief_id: int,
        voice_id: Optional[str] = None,
        brief_type: str = 'daily_brief',
        brief_run_id: Optional[int] = None
    ) -> Optional[AudioGenerationJob]:
        """
        Create a new audio generation job for a brief (DailyBrief or BriefRun).

        Uses database-level constraints to prevent race conditions.

        Args:
            brief_id: ID of the daily brief (if brief_type='daily_brief')
            voice_id: Voice preset to use (optional)
            brief_type: 'daily_brief' or 'brief_run'
            brief_run_id: ID of the brief run (if brief_type='brief_run')

        Returns:
            AudioGenerationJob instance, or None if creation fails
        """
        try:
            from app.models import BriefRun, BriefRunItem
            
            # Get brief and items based on type
            if brief_type == 'brief_run':
                brief_run = BriefRun.query.get(brief_run_id) if brief_run_id else None
                if not brief_run:
                    logger.error(f"BriefRun {brief_run_id} not found")
                    return None
                items = brief_run.items.order_by(BriefRunItem.position).all()
                total_items = len(items)
                lookup_id = brief_run_id
            else:
                brief = DailyBrief.query.get(brief_id)
                if not brief:
                    logger.error(f"Brief {brief_id} not found")
                    return None
                items = brief.items.order_by(BriefItem.position).all()
                total_items = len(items)
                lookup_id = brief_id

            if total_items == 0:
                logger.warning(f"{brief_type} {lookup_id} has no items")
                return None

            # Check if active job already exists (queued or processing)
            if brief_type == 'brief_run':
                existing = AudioGenerationJob.query.filter(
                    AudioGenerationJob.brief_run_id == brief_run_id,
                    AudioGenerationJob.brief_type == 'brief_run',
                    AudioGenerationJob.status.in_(['queued', 'processing'])
                ).first()
            else:
                existing = AudioGenerationJob.query.filter(
                    AudioGenerationJob.brief_id == brief_id,
                    AudioGenerationJob.brief_type == 'daily_brief',
                    AudioGenerationJob.status.in_(['queued', 'processing'])
                ).first()

            if existing:
                # Check if it's a stale job (stuck in processing)
                if existing.status == 'processing' and existing.started_at:
                    stale_threshold = datetime.utcnow() - timedelta(minutes=JOB_TIMEOUT_MINUTES)
                    if existing.started_at < stale_threshold:
                        logger.warning(f"Found stale job {existing.id}, marking as failed")
                        existing.status = 'failed'
                        existing.error_message = 'Job timed out'
                        db.session.commit()
                        # Continue to create new job
                    else:
                        logger.info(f"Job {existing.id} already processing for brief {brief_id}")
                        return existing
                else:
                    logger.info(f"Job {existing.id} already queued for brief {brief_id}")
                    return existing

            # Create new job
            job = AudioGenerationJob(
                brief_type=brief_type,
                brief_id=brief_id if brief_type == 'daily_brief' else None,
                brief_run_id=brief_run_id if brief_type == 'brief_run' else None,
                voice_id=voice_id or XTTSClient.DEFAULT_VOICE,
                status='queued',
                total_items=total_items,
                completed_items=0
            )

            db.session.add(job)

            try:
                db.session.commit()
                logger.info(f"Created audio generation job {job.id} for {brief_type} {lookup_id} ({total_items} items)")
                return job
            except IntegrityError:
                # Another request created a job between our check and insert
                db.session.rollback()
                # Return the existing job
                if brief_type == 'brief_run':
                    existing = AudioGenerationJob.query.filter(
                        AudioGenerationJob.brief_run_id == brief_run_id,
                        AudioGenerationJob.brief_type == 'brief_run',
                        AudioGenerationJob.status.in_(['queued', 'processing'])
                    ).first()
                else:
                    existing = AudioGenerationJob.query.filter(
                        AudioGenerationJob.brief_id == brief_id,
                        AudioGenerationJob.brief_type == 'daily_brief',
                        AudioGenerationJob.status.in_(['queued', 'processing'])
                    ).first()
                if existing:
                    logger.info(f"Concurrent job creation detected, returning existing job {existing.id}")
                    return existing
                return None

        except Exception as e:
            logger.error(f"Failed to create audio generation job: {e}", exc_info=True)
            db.session.rollback()
            return None

    def recover_stale_jobs(self) -> int:
        """
        Find and mark stale jobs as failed.

        Called periodically by the scheduler to clean up jobs that got stuck.

        Returns:
            Number of jobs recovered
        """
        try:
            stale_threshold = datetime.utcnow() - timedelta(minutes=JOB_TIMEOUT_MINUTES)

            stale_jobs = AudioGenerationJob.query.filter(
                AudioGenerationJob.status == 'processing',
                AudioGenerationJob.started_at < stale_threshold
            ).all()

            recovered = 0
            for job in stale_jobs:
                logger.warning(f"Recovering stale job {job.id} (started at {job.started_at})")
                job.status = 'failed'
                job.error_message = f'Job timed out after {JOB_TIMEOUT_MINUTES} minutes'
                recovered += 1

            if recovered > 0:
                db.session.commit()
                logger.info(f"Recovered {recovered} stale audio generation jobs")

            return recovered

        except Exception as e:
            logger.error(f"Failed to recover stale jobs: {e}", exc_info=True)
            db.session.rollback()
            return 0
    
    def process_job(self, job_id: int) -> bool:
        """
        Process an audio generation job.

        Tracks both completed and failed items separately for better visibility.
        Uses database-level locking to prevent concurrent processing.

        Args:
            job_id: ID of the audio generation job

        Returns:
            True if job completed successfully, False otherwise
        """
        try:
            # Use row-level locking to prevent concurrent processing
            job = AudioGenerationJob.query.with_for_update().get(job_id)
            if not job:
                logger.error(f"Job {job_id} not found")
                return False

            if job.status != 'queued':
                logger.warning(f"Job {job_id} is not queued (status: {job.status})")
                db.session.rollback()  # Release lock
                return False

            # Update status to processing
            job.status = 'processing'
            job.started_at = datetime.utcnow()
            job.progress = 0
            job.completed_items = 0
            job.failed_items = 0
            db.session.commit()

            # Get brief/run and items based on type
            from app.models import BriefRun, BriefRunItem
            
            if job.brief_type == 'brief_run':
                brief_run = BriefRun.query.get(job.brief_run_id)
                if not brief_run:
                    job.status = 'failed'
                    job.error_message = "BriefRun not found"
                    db.session.commit()
                    return False
                items = brief_run.items.order_by(BriefRunItem.position).all()
                item_model = BriefRunItem
            else:
                brief = DailyBrief.query.get(job.brief_id)
                if not brief:
                    job.status = 'failed'
                    job.error_message = "Brief not found"
                    db.session.commit()
                    return False
                items = brief.items.order_by(BriefItem.position).all()
                item_model = BriefItem

            # Generate audio for each item
            completed = 0
            failed = 0
            
            # Validate we have items to process
            if not items:
                job.status = 'failed'
                job.error_message = "Brief has no items to process"
                db.session.commit()
                return False

            # Extract item data before long operations to avoid connection timeouts
            item_data_list = []
            for item in items:
                item_data = {
                    'id': item.id,
                    'audio_url': item.audio_url,
                    'headline': item.headline if hasattr(item, 'headline') else None,
                    'summary_bullets': item.summary_bullets if hasattr(item, 'summary_bullets') else None,
                    'personal_impact': item.personal_impact if hasattr(item, 'personal_impact') else None,
                    'so_what': item.so_what if hasattr(item, 'so_what') else None,
                    'content_markdown': item.content_markdown[:500] if hasattr(item, 'content_markdown') and item.content_markdown else None,
                }
                item_data_list.append(item_data)
            
            # Close session to avoid timeout during long audio generation
            db.session.close()

            for item_data in item_data_list:
                item_id = item_data['id']
                try:
                    # Skip if audio already exists
                    if item_data['audio_url']:
                        logger.info(f"Item {item_id} already has audio, skipping")
                        completed += 1
                        # Refresh connection and update job
                        job = AudioGenerationJob.query.get(job_id)
                        job.completed_items = completed
                        job.failed_items = failed
                        db.session.commit()
                        db.session.close()
                        continue

                    # Build text content for audio (works for both BriefItem and BriefRunItem)
                    text_parts = []
                    if item_data['headline']:
                        text_parts.append(item_data['headline'])
                    if item_data['summary_bullets']:
                        text_parts.append(". ".join(item_data['summary_bullets']))
                    # BriefItem has personal_impact and so_what, BriefRunItem has content_markdown
                    if item_data['personal_impact']:
                        text_parts.append(item_data['personal_impact'])
                    if item_data['so_what']:
                        text_parts.append(item_data['so_what'])
                    if item_data['content_markdown']:
                        text_parts.append(item_data['content_markdown'])

                    audio_text = ". ".join(text_parts)
                    
                    # Ensure text is properly encoded
                    if isinstance(audio_text, bytes):
                        try:
                            audio_text = audio_text.decode('utf-8')
                        except UnicodeDecodeError:
                            logger.error(f"Failed to decode text for item {item_id}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            continue

                    if not audio_text or len(audio_text.strip()) == 0:
                        logger.warning(f"Item {item_id} has no text content, counting as failed")
                        failed += 1
                        job = AudioGenerationJob.query.get(job_id)
                        job.completed_items = completed
                        job.failed_items = failed
                        db.session.commit()
                        db.session.close()
                        continue

                    # Generate audio file (this is the LONG operation - 5+ minutes)
                    logger.info(f"Generating audio for item {item_id} ({len(audio_text)} chars)...")
                    audio_path = None
                    
                    # Get voice_id before closing session
                    job = AudioGenerationJob.query.get(job_id)
                    voice_id = job.voice_id
                    brief_type = job.brief_type
                    brief_id = job.brief_id
                    brief_run_id = job.brief_run_id
                    db.session.close()
                    
                    try:
                        audio_path = self.xtts_client.generate_audio(
                            text=audio_text,
                            voice_id=voice_id
                        )

                        if not audio_path:
                            logger.error(f"Failed to generate audio for item {item_id}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            continue

                        # Validate temp file exists and is readable
                        if not os.path.exists(audio_path) or not os.path.isfile(audio_path):
                            logger.error(f"Generated audio file does not exist: {audio_path}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            continue

                        # Read audio file (stream in chunks for memory efficiency on Replit)
                        try:
                            with open(audio_path, 'rb') as f:
                                audio_data = f.read()
                            
                            # Validate audio data is not empty
                            if not audio_data or len(audio_data) == 0:
                                raise ValueError("Generated audio file is empty")
                                
                        except Exception as read_error:
                            logger.error(f"Failed to read audio file for item {item_id}: {read_error}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            # Cleanup temp file on read error
                            if audio_path and os.path.exists(audio_path):
                                try:
                                    os.remove(audio_path)
                                except Exception:
                                    pass
                            continue

                        # Generate filename (sanitize to prevent path traversal)
                        timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
                        text_hash = hashlib.md5(audio_text.encode('utf-8')).hexdigest()[:8]
                        if brief_type == 'brief_run':
                            filename = f"brief_run_{brief_run_id}_item_{item_id}_{timestamp}_{text_hash}.wav"
                        else:
                            filename = f"brief_{brief_id}_item_{item_id}_{timestamp}_{text_hash}.wav"
                        
                        # Additional filename validation
                        if '..' in filename or '/' in filename or '\\' in filename:
                            logger.error(f"Invalid filename generated: {filename}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            # Cleanup temp file
                            if audio_path and os.path.exists(audio_path):
                                try:
                                    os.remove(audio_path)
                                except Exception:
                                    pass
                            continue

                        # Save to storage
                        audio_url = self.storage.save(audio_data, filename)

                        # Free memory immediately after save
                        del audio_data

                        if not audio_url:
                            logger.error(f"Failed to save audio for item {item_id}")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            # Cleanup temp file on storage error
                            if audio_path and os.path.exists(audio_path):
                                try:
                                    os.remove(audio_path)
                                except Exception:
                                    pass
                            continue

                        # Re-query item from database with fresh connection
                        item = item_model.query.get(item_id)
                        if not item:
                            logger.error(f"Item {item_id} no longer exists")
                            failed += 1
                            job = AudioGenerationJob.query.get(job_id)
                            job.completed_items = completed
                            job.failed_items = failed
                            db.session.commit()
                            db.session.close()
                            continue
                        
                        # Update item
                        item.audio_url = audio_url
                        item.audio_voice_id = voice_id
                        item.audio_generated_at = datetime.utcnow()

                    finally:
                        # Always cleanup temp file, even on errors
                        if audio_path and os.path.exists(audio_path):
                            try:
                                os.remove(audio_path)
                            except Exception as cleanup_error:
                                logger.warning(f"Failed to cleanup temp file {audio_path}: {cleanup_error}")

                    completed += 1
                    # Refresh job from database
                    job = AudioGenerationJob.query.get(job_id)
                    job.completed_items = completed
                    job.failed_items = failed
                    db.session.commit()
                    db.session.close()

                    logger.info(f"Generated audio for item {item_id} ({completed}/{len(item_data_list)})")

                except Exception as e:
                    logger.error(f"Error processing item {item_id}: {e}", exc_info=True)
                    failed += 1
                    try:
                        job = AudioGenerationJob.query.get(job_id)
                        job.completed_items = completed
                        job.failed_items = failed
                        db.session.commit()
                        db.session.close()
                    except Exception:
                        db.session.rollback()
                        db.session.close()
                    continue

            # Mark job as completed
            job = AudioGenerationJob.query.get(job_id)
            job.status = 'completed'
            job.completed_at = datetime.utcnow()
            db.session.commit()

            if failed > 0:
                logger.warning(f"Audio generation job {job_id} completed with {failed} failures ({completed} succeeded)")
            else:
                logger.info(f"Audio generation job {job_id} completed successfully ({completed} items)")

            return True

        except Exception as e:
            logger.error(f"Failed to process audio generation job {job_id}: {e}", exc_info=True)
            db.session.rollback()

            # Update job status
            try:
                job = AudioGenerationJob.query.get(job_id)
                if job:
                    job.status = 'failed'
                    job.error_message = str(e)[:500]  # Truncate long error messages
                    db.session.commit()
            except Exception:
                pass

            return False
    
    def get_job_status(self, job_id: int) -> Optional[dict]:
        """
        Get status of an audio generation job.
        
        Args:
            job_id: ID of the audio generation job
        
        Returns:
            Job status dictionary, or None if job not found
        """
        job = AudioGenerationJob.query.get(job_id)
        if not job:
            return None
        
        return job.to_dict()


# Global generator instance
audio_generator = AudioGenerator()
