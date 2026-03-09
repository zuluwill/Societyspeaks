"""Consensus job queue helpers."""

from datetime import timedelta
import logging
import os

from sqlalchemy import func

from app import db
from app.analytics.events import record_event
from app.lib.time import utcnow_naive
from app.lib.consensus_engine import (
    build_oversize_consensus_results,
    get_consensus_execution_plan,
    run_consensus_analysis,
    save_consensus_analysis,
)
from app.models import ConsensusJob, Discussion, StatementVote

logger = logging.getLogger(__name__)


def _discussion_vote_window_key(discussion_id):
    """
    Build a deterministic vote-window bucket key for deduping.
    Uses latest vote timestamp rounded to the hour.
    """
    latest_vote_at = db.session.query(
        func.max(func.coalesce(StatementVote.updated_at, StatementVote.created_at))
    ).filter(
        StatementVote.discussion_id == discussion_id
    ).scalar()

    if not latest_vote_at:
        return "no_votes"
    return latest_vote_at.replace(minute=0, second=0, microsecond=0).strftime("%Y%m%d%H")


def build_consensus_dedupe_key(discussion_id):
    return f"discussion:{discussion_id}:vote_window:{_discussion_vote_window_key(discussion_id)}"


def enqueue_consensus_job(discussion_id, requested_by_user_id=None, reason='manual'):
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion or not discussion.has_native_statements:
        return None, False, "Discussion not eligible for native consensus jobs."

    dedupe_key = build_consensus_dedupe_key(discussion_id)
    existing = ConsensusJob.query.filter(
        ConsensusJob.discussion_id == discussion_id,
        ConsensusJob.dedupe_key == dedupe_key,
        ConsensusJob.status.in_(list(ConsensusJob.ACTIVE_STATUSES))
    ).order_by(ConsensusJob.created_at.desc()).first()
    if existing:
        return existing, False, "Analysis already queued or running for current vote window."

    job = ConsensusJob(
        discussion_id=discussion_id,
        requested_by_user_id=requested_by_user_id,
        dedupe_key=dedupe_key,
        reason=reason or 'manual',
        status=ConsensusJob.STATUS_QUEUED,
        queued_at=utcnow_naive(),
        max_attempts=3,
        timeout_seconds=900,
    )
    db.session.add(job)
    db.session.commit()
    return job, True, "Analysis queued."


def mark_stale_consensus_jobs():
    now = utcnow_naive()
    running_jobs = ConsensusJob.query.filter_by(status=ConsensusJob.STATUS_RUNNING).all()
    stale_count = 0
    for job in running_jobs:
        if job.started_at and (now - job.started_at) > timedelta(seconds=max(0, job.timeout_seconds or 0)):
            job.status = ConsensusJob.STATUS_STALE
            job.error_message = "Job timed out while running."
            job.completed_at = now
            stale_count += 1
    if stale_count:
        db.session.commit()
    return stale_count


def get_consensus_queue_metrics():
    """Lightweight queue metrics for worker logs and health telemetry."""
    now = utcnow_naive()
    queued_count = ConsensusJob.query.filter_by(status=ConsensusJob.STATUS_QUEUED).count()
    oldest = ConsensusJob.query.filter_by(status=ConsensusJob.STATUS_QUEUED).order_by(
        ConsensusJob.queued_at.asc(), ConsensusJob.id.asc()
    ).first()
    lag_seconds = int((now - oldest.queued_at).total_seconds()) if oldest and oldest.queued_at else 0
    running_count = ConsensusJob.query.filter_by(status=ConsensusJob.STATUS_RUNNING).count()
    dead_letter_count = ConsensusJob.query.filter_by(status=ConsensusJob.STATUS_DEAD_LETTER).count()
    return {
        "queued_count": queued_count,
        "running_count": running_count,
        "dead_letter_count": dead_letter_count,
        "queue_lag_seconds": max(0, lag_seconds),
    }


def process_next_consensus_job():
    """
    Claim and execute the next queued consensus job.
    Returns True if a job was processed (success or failure), else False.
    """
    # Explicit safety rail: heavy clustering should run in worker processes only.
    # Set CONSENSUS_WORKER_PROCESS=1 in worker entrypoints, or override with
    # CONSENSUS_ALLOW_IN_PROCESS_EXECUTION=true for emergency scheduler fallback.
    from flask import current_app
    worker_process = os.getenv("CONSENSUS_WORKER_PROCESS", "0").strip() == "1"
    allow_in_process = bool(current_app.config.get("CONSENSUS_ALLOW_IN_PROCESS_EXECUTION", False))
    if not worker_process and not allow_in_process:
        logger.warning(
            "Skipping consensus job execution in non-worker process "
            "(set CONSENSUS_WORKER_PROCESS=1 or CONSENSUS_ALLOW_IN_PROCESS_EXECUTION=true to override)."
        )
        return False

    # Use SELECT FOR UPDATE SKIP LOCKED so concurrent workers never claim the
    # same job.  Falls back to plain SELECT on dialects that don't support it
    # (e.g. SQLite during tests).
    bind = db.session.get_bind()
    if bind.dialect.name == 'postgresql':
        job = ConsensusJob.query.filter_by(
            status=ConsensusJob.STATUS_QUEUED
        ).order_by(ConsensusJob.queued_at.asc(), ConsensusJob.id.asc()).with_for_update(skip_locked=True).first()
    else:
        job = ConsensusJob.query.filter_by(
            status=ConsensusJob.STATUS_QUEUED
        ).order_by(ConsensusJob.queued_at.asc(), ConsensusJob.id.asc()).first()

    if not job:
        return False

    job.status = ConsensusJob.STATUS_RUNNING
    job.started_at = utcnow_naive()
    job.attempts = (job.attempts or 0) + 1
    job.error_message = None
    db.session.commit()

    try:
        plan = get_consensus_execution_plan(job.discussion_id, db)
        if not plan['is_ready']:
            job.status = ConsensusJob.STATUS_FAILED
            job.error_message = f"Not ready for clustering: {plan['message']}"
            job.completed_at = utcnow_naive()
            db.session.commit()
            return True

        # Route on plan to avoid a second get_consensus_execution_plan() call inside
        # run_consensus_analysis (which would be a redundant DB round-trip).
        if plan['mode'] == 'sampled_incremental':
            results = build_oversize_consensus_results(job.discussion_id, db, plan)
        else:
            results = run_consensus_analysis(job.discussion_id, db, method='agglomerative')
        if results is None:
            raise RuntimeError("Consensus engine returned no result.")

        analysis = save_consensus_analysis(job.discussion_id, results, db)
        job.analysis_id = analysis.id if analysis else None
        job.status = ConsensusJob.STATUS_COMPLETED
        job.completed_at = utcnow_naive()
        db.session.commit()
        if analysis and analysis.discussion:
            record_event(
                'analysis_generated',
                user_id=job.requested_by_user_id,
                discussion_id=job.discussion_id,
                programme_id=analysis.discussion.programme_id,
                country=analysis.discussion.country,
                source='consensus_worker',
                event_metadata={'analysis_id': analysis.id, 'job_id': job.id}
            )
        return True

    except Exception as exc:
        logger.error(f"Consensus job {job.id} failed: {exc}", exc_info=True)
        if (job.attempts or 0) >= (job.max_attempts or 1):
            job.status = ConsensusJob.STATUS_DEAD_LETTER
        else:
            job.status = ConsensusJob.STATUS_QUEUED
            job.queued_at = utcnow_naive()
        job.error_message = str(exc)[:1000]
        job.completed_at = utcnow_naive() if job.status == ConsensusJob.STATUS_DEAD_LETTER else None
        db.session.commit()
        return True
