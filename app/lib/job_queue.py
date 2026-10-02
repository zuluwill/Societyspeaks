"""Background job queue.

Work that must not run inside a web request (LLM calls, PDF rendering, email
fan-out) is persisted as a ``BackgroundJob`` and drained by the worker
(``scripts/run_consensus_worker.py``). A job is claimed with SKIP LOCKED,
retried with backoff until ``max_attempts``, then dead-lettered.

Handlers register by kind::

    @job_handler('consultation.draft_statements')
    def draft_statements(job):
        ...
        return {'statements': 12}   # stored on job.result

A handler that raises is retried. A handler should do its own degrading
(fall back to a template, hold for a human) rather than rely on the retry:
the dead-letter hook is the last resort, and it pages operations.
"""
import logging
import os
from datetime import timedelta
from typing import Callable, Dict, Optional, Tuple

from sqlalchemy.exc import IntegrityError

from app import db
from app.lib.time import utcnow_naive
from app.models import BackgroundJob

logger = logging.getLogger(__name__)

# Ops pages on recently exhausted jobs only, as for the consensus queue.
DEAD_LETTER_ALERT_LOOKBACK = timedelta(hours=24)
_RETRY_BASE_SECONDS = 20

_HANDLERS: Dict[str, Callable] = {}
_DEAD_LETTER_HOOKS: Dict[str, Callable] = {}


def job_handler(kind: str):
    """Register the function that runs jobs of ``kind``."""
    def decorator(fn):
        _HANDLERS[kind] = fn
        return fn
    return decorator


def on_dead_letter(kind: str):
    """Register a function called once when a job of ``kind`` exhausts its attempts."""
    def decorator(fn):
        _DEAD_LETTER_HOOKS[kind] = fn
        return fn
    return decorator


def enqueue_job(
    kind: str,
    *,
    payload: Optional[dict] = None,
    consultation_id: Optional[int] = None,
    user_id: Optional[int] = None,
    dedupe_key: Optional[str] = None,
    max_attempts: int = 3,
    timeout_seconds: int = 300,
    delay_seconds: int = 0,
    commit: bool = True,
) -> Tuple[BackgroundJob, bool]:
    """Queue a job. Returns ``(job, created)``.

    With a ``dedupe_key``, an identical job that is still queued or running is
    returned instead of adding a second one.
    """
    def _active_duplicate():
        return BackgroundJob.query.filter(
            BackgroundJob.dedupe_key == dedupe_key,
            BackgroundJob.status.in_(list(BackgroundJob.ACTIVE_STATUSES)),
        ).order_by(BackgroundJob.id.desc()).first()

    if dedupe_key:
        existing = _active_duplicate()
        if existing:
            return existing, False

    now = utcnow_naive()
    job = BackgroundJob(
        kind=kind,
        payload=payload or {},
        consultation_id=consultation_id,
        user_id=user_id,
        dedupe_key=dedupe_key or f'{kind}:{now.isoformat()}:{os.urandom(4).hex()}',
        status=BackgroundJob.STATUS_QUEUED,
        max_attempts=max_attempts,
        timeout_seconds=timeout_seconds,
        queued_at=now,
        run_after=now + timedelta(seconds=max(0, delay_seconds)),
    )
    try:
        with db.session.begin_nested():
            db.session.add(job)
    except IntegrityError:
        # Two requests queued the same work at once; the unique index let one in.
        existing = _active_duplicate() if dedupe_key else None
        if existing is None:
            raise
        return existing, False
    if commit:
        db.session.commit()
    return job, True


def latest_job(kind: str, consultation_id: int) -> Optional[BackgroundJob]:
    return BackgroundJob.query.filter_by(
        kind=kind, consultation_id=consultation_id,
    ).order_by(BackgroundJob.id.desc()).first()


def _claim_next_job() -> Optional[BackgroundJob]:
    now = utcnow_naive()
    query = BackgroundJob.query.filter(
        BackgroundJob.status == BackgroundJob.STATUS_QUEUED,
        BackgroundJob.run_after <= now,
    ).order_by(BackgroundJob.run_after.asc(), BackgroundJob.id.asc())
    if db.session.get_bind().dialect.name == 'postgresql':
        query = query.with_for_update(skip_locked=True)
    job = query.first()
    if not job:
        return None
    job.status = BackgroundJob.STATUS_RUNNING
    job.started_at = now
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.session.commit()
    return job


def _retry_or_bury(job: BackgroundJob, error: str) -> None:
    """Requeue with backoff, or dead-letter once attempts are exhausted."""
    now = utcnow_naive()
    job.error_message = (error or '')[:1000]
    if (job.attempts or 0) >= (job.max_attempts or 1):
        job.status = BackgroundJob.STATUS_DEAD_LETTER
        job.completed_at = now
        db.session.commit()
        hook = _DEAD_LETTER_HOOKS.get(job.kind)
        if hook:
            try:
                hook(job)
                db.session.commit()
            except Exception:
                db.session.rollback()
                logger.exception('Dead-letter hook failed for job %s (%s)', job.id, job.kind)
        return
    job.status = BackgroundJob.STATUS_QUEUED
    job.started_at = None
    job.run_after = now + timedelta(seconds=_RETRY_BASE_SECONDS * (2 ** max(0, (job.attempts or 1) - 1)))
    db.session.commit()


def process_next_job() -> bool:
    """Claim and run the next due job. True if a job was processed."""
    try:
        job = _claim_next_job()
    except Exception as db_err:
        logger.warning('DB error claiming background job: %s', db_err)
        db.session.rollback()
        return False
    if not job:
        return False

    handler = _HANDLERS.get(job.kind)
    job_id, kind = job.id, job.kind
    try:
        if handler is None:
            raise LookupError(f'No handler registered for job kind {kind!r}')
        result = handler(job)
        job = db.session.get(BackgroundJob, job_id)
        # The job's row goes when its consultation is deleted mid-run.
        if job is not None:
            job.result = result if isinstance(result, dict) else None
            job.status = BackgroundJob.STATUS_COMPLETED
            job.completed_at = utcnow_naive()
            db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.error('Background job %s (%s) failed: %s', job_id, kind, exc, exc_info=True)
        job = db.session.get(BackgroundJob, job_id)
        if job is not None:
            _retry_or_bury(job, str(exc))
    return True


def drain_jobs(limit: int = 50) -> int:
    """Run due jobs until none are left (tests, CLI, in-process development)."""
    processed = 0
    while processed < limit and process_next_job():
        processed += 1
    return processed


def recover_stale_jobs() -> int:
    """Return timed-out running jobs to the queue (or bury them if exhausted).

    A job is left "running" when its worker dies mid-job. Unlike the consensus
    queue, these are retried automatically: nobody should have to restart a
    report by hand.
    """
    stale = [
        job for job in BackgroundJob.query.filter_by(status=BackgroundJob.STATUS_RUNNING).all()
        if job.is_timed_out
    ]
    for job in stale:
        _retry_or_bury(job, 'Job timed out while running.')
    return len(stale)


def get_queue_metrics() -> dict:
    """Queue metrics in the shape ``build_queue_lag_alerts`` expects."""
    now = utcnow_naive()
    due = BackgroundJob.query.filter(
        BackgroundJob.status == BackgroundJob.STATUS_QUEUED,
        BackgroundJob.run_after <= now,
    )
    oldest = due.order_by(BackgroundJob.run_after.asc()).first()
    return {
        'queued_count': due.count(),
        'running_count': BackgroundJob.query.filter_by(status=BackgroundJob.STATUS_RUNNING).count(),
        'dead_letter_count': BackgroundJob.query.filter_by(status=BackgroundJob.STATUS_DEAD_LETTER).count(),
        'recent_dead_letter_count': BackgroundJob.query.filter(
            BackgroundJob.status == BackgroundJob.STATUS_DEAD_LETTER,
            BackgroundJob.completed_at.isnot(None),
            BackgroundJob.completed_at >= now - DEAD_LETTER_ALERT_LOOKBACK,
        ).count(),
        'queue_lag_seconds': max(0, int((now - oldest.run_after).total_seconds())) if oldest else 0,
    }
