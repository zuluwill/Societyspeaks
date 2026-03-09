"""Programme export queue helpers."""

import logging
from datetime import timedelta

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from app import db
from app.lib.time import utcnow_naive
from app.models import Programme, ProgrammeExportJob
from app.programmes.export import (
    _export_filename,
    generate_programme_export_csv_bytes,
    generate_programme_export_json_bytes,
)
from app.storage_utils import upload_bytes_to_object_storage, download_bytes_from_object_storage

logger = logging.getLogger(__name__)

DOWNLOAD_SALT = "programme-export-download"


def _dedupe_key(programme_id, export_format, cohort_slug):
    return f"programme:{programme_id}:format:{export_format}:cohort:{cohort_slug or 'all'}"


def enqueue_programme_export_job(programme_id, requested_by_user_id, export_format='csv', cohort_slug=None):
    export_format = (export_format or 'csv').strip().lower()
    if export_format not in ('csv', 'json'):
        export_format = 'csv'

    dedupe_key = _dedupe_key(programme_id, export_format, cohort_slug)
    existing = ProgrammeExportJob.query.filter(
        ProgrammeExportJob.programme_id == programme_id,
        ProgrammeExportJob.requested_by_user_id == requested_by_user_id,
        ProgrammeExportJob.dedupe_key == dedupe_key,
        ProgrammeExportJob.status.in_(list(ProgrammeExportJob.ACTIVE_STATUSES))
    ).order_by(ProgrammeExportJob.created_at.desc()).first()
    if existing:
        return existing, False, "Export already queued or running."

    job = ProgrammeExportJob(
        programme_id=programme_id,
        requested_by_user_id=requested_by_user_id,
        export_format=export_format,
        cohort_slug=cohort_slug,
        dedupe_key=dedupe_key,
        status=ProgrammeExportJob.STATUS_QUEUED,
        queued_at=utcnow_naive(),
        max_attempts=3,
        timeout_seconds=900,
    )
    db.session.add(job)
    db.session.commit()
    return job, True, "Export queued."


def _serializer(secret_key):
    return URLSafeTimedSerializer(secret_key, salt=DOWNLOAD_SALT)


def generate_export_download_token(secret_key, job_id, user_id):
    return _serializer(secret_key).dumps({"job_id": int(job_id), "user_id": int(user_id)})


def verify_export_download_token(secret_key, token, max_age_seconds=3600):
    try:
        payload = _serializer(secret_key).loads(token, max_age=max_age_seconds)
        return payload, None
    except SignatureExpired:
        return None, "expired"
    except BadSignature:
        return None, "invalid"


def mark_stale_programme_export_jobs():
    now = utcnow_naive()
    running = ProgrammeExportJob.query.filter_by(status=ProgrammeExportJob.STATUS_RUNNING).all()
    stale_count = 0
    for job in running:
        if job.started_at and (now - job.started_at) > timedelta(seconds=max(0, job.timeout_seconds or 0)):
            job.status = ProgrammeExportJob.STATUS_STALE
            job.error_message = "Export job timed out while running."
            job.completed_at = now
            stale_count += 1
    if stale_count:
        db.session.commit()
    return stale_count


def get_programme_export_queue_metrics():
    now = utcnow_naive()
    queued_count = ProgrammeExportJob.query.filter_by(status=ProgrammeExportJob.STATUS_QUEUED).count()
    oldest = ProgrammeExportJob.query.filter_by(status=ProgrammeExportJob.STATUS_QUEUED).order_by(
        ProgrammeExportJob.queued_at.asc(), ProgrammeExportJob.id.asc()
    ).first()
    lag_seconds = int((now - oldest.queued_at).total_seconds()) if oldest and oldest.queued_at else 0
    running_count = ProgrammeExportJob.query.filter_by(status=ProgrammeExportJob.STATUS_RUNNING).count()
    dead_letter_count = ProgrammeExportJob.query.filter_by(status=ProgrammeExportJob.STATUS_DEAD_LETTER).count()
    return {
        "queued_count": queued_count,
        "running_count": running_count,
        "dead_letter_count": dead_letter_count,
        "queue_lag_seconds": max(0, lag_seconds),
    }


def process_next_programme_export_job():
    bind = db.session.get_bind()
    if bind.dialect.name == 'postgresql':
        job = ProgrammeExportJob.query.filter_by(
            status=ProgrammeExportJob.STATUS_QUEUED
        ).order_by(ProgrammeExportJob.queued_at.asc(), ProgrammeExportJob.id.asc()).with_for_update(skip_locked=True).first()
    else:
        job = ProgrammeExportJob.query.filter_by(
            status=ProgrammeExportJob.STATUS_QUEUED
        ).order_by(ProgrammeExportJob.queued_at.asc(), ProgrammeExportJob.id.asc()).first()

    if not job:
        return False

    job.status = ProgrammeExportJob.STATUS_RUNNING
    job.started_at = utcnow_naive()
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.session.commit()

    try:
        programme = db.session.get(Programme, job.programme_id)
        if not programme:
            raise RuntimeError("Programme not found for export job.")

        if job.export_format == 'json':
            data = generate_programme_export_json_bytes(programme, cohort_slug=job.cohort_slug)
            content_type = 'application/json'
        else:
            data = generate_programme_export_csv_bytes(programme, cohort_slug=job.cohort_slug)
            content_type = 'text/csv'

        filename = _export_filename(programme.slug, job.cohort_slug, job.export_format)
        storage_key = f"programme_exports/{programme.id}/{job.id}/{filename}"
        uploaded = upload_bytes_to_object_storage(storage_key, data)
        if not uploaded:
            raise RuntimeError("Failed to upload export artifact to object storage.")

        job.storage_key = storage_key
        job.artifact_filename = filename
        job.content_type = content_type
        job.artifact_size_bytes = len(data)
        job.status = ProgrammeExportJob.STATUS_COMPLETED
        job.completed_at = utcnow_naive()
        db.session.commit()
        return True
    except Exception as exc:
        logger.error(f"Programme export job {job.id} failed: {exc}", exc_info=True)
        if (job.attempts or 0) >= (job.max_attempts or 1):
            job.status = ProgrammeExportJob.STATUS_DEAD_LETTER
        else:
            job.status = ProgrammeExportJob.STATUS_QUEUED
            job.queued_at = utcnow_naive()
        job.error_message = str(exc)[:1000]
        job.completed_at = utcnow_naive() if job.status == ProgrammeExportJob.STATUS_DEAD_LETTER else None
        db.session.commit()
        return True


def read_export_artifact_bytes(job):
    if not job or not job.storage_key:
        return None
    return download_bytes_from_object_storage(job.storage_key)
