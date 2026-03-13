"""
Audio Generation Service

Audio generation via XTTS has been removed. This module is kept as a stub
so that existing references to AudioGenerator/audio_generator continue to
import without errors. All generation methods are no-ops.
"""

import logging
from typing import Optional
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive

from app import db
from app.models import AudioGenerationJob

logger = logging.getLogger(__name__)

JOB_TIMEOUT_MINUTES = 30


class AudioGenerator:
    """Stub audio generator. Audio generation is not available."""

    def create_generation_job(
        self,
        brief_id: int,
        voice_id: Optional[str] = None,
        brief_type: str = 'daily_brief',
        brief_run_id: Optional[int] = None
    ) -> None:
        logger.debug("Audio generation is disabled; create_generation_job is a no-op")
        return None

    def recover_stale_jobs(self) -> int:
        try:
            stale_threshold = utcnow_naive() - timedelta(minutes=JOB_TIMEOUT_MINUTES)
            stale_jobs = AudioGenerationJob.query.filter(
                AudioGenerationJob.status == 'processing',
                AudioGenerationJob.started_at < stale_threshold
            ).all()
            recovered = 0
            for job in stale_jobs:
                job.status = 'failed'
                job.error_message = 'Audio generation is disabled'
                recovered += 1
            if recovered > 0:
                db.session.commit()
            return recovered
        except Exception as e:
            logger.error(f"Failed to recover stale audio jobs: {e}")
            db.session.rollback()
            return 0

    def process_job(self, job_id: int) -> bool:
        logger.debug("Audio generation is disabled; process_job is a no-op")
        return False

    def get_job_status(self, job_id: int) -> Optional[dict]:
        job = db.session.get(AudioGenerationJob, job_id)
        if not job:
            return None
        return job.to_dict()


audio_generator = AudioGenerator()
