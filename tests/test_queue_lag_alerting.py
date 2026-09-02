"""A dead worker must be loud, not silent.

Consensus and programme-export jobs are drained by a separate Render service
(societyspeaks-consensus-worker). If that service dies, jobs sit queued while
the results page keeps telling the user "results will appear once processing
completes" — a promise the product cannot keep, with nothing paging anyone.

The scheduler is the only always-on process able to observe that, so the
queue-lag checks live in its 5-minute stale-job sweeps.
"""

from datetime import timedelta
from pathlib import Path

from app.lib.time import utcnow_naive


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def _queued_consensus_job(db, age_seconds: int):
    from app.models import ConsensusJob, Discussion, generate_slug

    discussion = Discussion(
        title='Queue Lag Discussion',
        slug=generate_slug('Queue Lag Discussion'),
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()

    job = ConsensusJob(
        discussion_id=discussion.id,
        dedupe_key=f'discussion:{discussion.id}:test',
        reason='manual_trigger',
        status=ConsensusJob.STATUS_QUEUED,
        queued_at=utcnow_naive() - timedelta(seconds=age_seconds),
        max_attempts=3,
        timeout_seconds=900,
    )
    db.session.add(job)
    db.session.commit()
    return job


def test_queue_metrics_report_lag_for_a_stranded_job(db):
    """This is what a dead worker looks like from the scheduler's side."""
    from app.discussions.jobs import get_consensus_queue_metrics

    _queued_consensus_job(db, age_seconds=600)
    metrics = get_consensus_queue_metrics()

    assert metrics['queued_count'] == 1
    assert metrics['queue_lag_seconds'] >= 600
    assert metrics['running_count'] == 0


def test_empty_queue_reports_no_lag(db):
    """An idle queue must not look like a stuck one."""
    from app.discussions.jobs import get_consensus_queue_metrics

    metrics = get_consensus_queue_metrics()
    assert metrics['queued_count'] == 0
    assert metrics['queue_lag_seconds'] == 0
    assert metrics['dead_letter_count'] == 0


def test_lag_threshold_defaults_match_published_slo(app):
    """The alert thresholds must not drift from the SLO /admin/slo advertises."""
    slo_source = _read("app/admin/routes.py")
    assert '"consensus": 120' in slo_source
    assert '"exports": 300' in slo_source

    assert app.config['CONSENSUS_QUEUE_LAG_ALERT_SECONDS'] == 120
    assert app.config['EXPORT_QUEUE_LAG_ALERT_SECONDS'] == 300


def test_healthy_queue_raises_no_alert():
    from app.scheduler import build_queue_lag_alerts

    healthy = {'queued_count': 0, 'queue_lag_seconds': 0, 'dead_letter_count': 0}
    assert build_queue_lag_alerts('CONSENSUS', healthy, 120) == []


def test_job_waiting_under_threshold_raises_no_alert():
    """A job claimed within the worker's poll interval is normal, not a stall."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {'queued_count': 1, 'queue_lag_seconds': 5, 'dead_letter_count': 0}
    assert build_queue_lag_alerts('CONSENSUS', metrics, 120) == []


def test_stranded_job_raises_a_stuck_alert_naming_the_service():
    from app.scheduler import build_queue_lag_alerts

    metrics = {'queued_count': 2, 'queue_lag_seconds': 600, 'dead_letter_count': 0}
    alerts = build_queue_lag_alerts('CONSENSUS', metrics, 120)

    assert len(alerts) == 1
    assert 'CONSENSUS QUEUE STUCK' in alerts[0]
    assert 'societyspeaks-consensus-worker' in alerts[0]
    assert '600s' in alerts[0]


def test_long_running_job_is_progress_not_a_stall():
    """running_count must never trigger the stuck-queue alert."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {'queued_count': 0, 'running_count': 1,
               'queue_lag_seconds': 0, 'dead_letter_count': 0}
    assert build_queue_lag_alerts('CONSENSUS', metrics, 120) == []


def test_dead_letter_alerts_even_when_queue_is_drained():
    """Exhausted retries are a silent product failure and must page separately."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {'queued_count': 0, 'queue_lag_seconds': 0, 'dead_letter_count': 3}
    alerts = build_queue_lag_alerts('CONSENSUS', metrics, 120)

    assert len(alerts) == 1
    assert 'CONSENSUS DEAD LETTER' in alerts[0]


def test_both_queues_are_wired_into_the_scheduler_sweeps():
    source = _read("app/scheduler.py")
    assert "build_queue_lag_alerts('CONSENSUS'" in source
    assert "build_queue_lag_alerts('PROGRAMME EXPORT'" in source
    assert "get_consensus_queue_metrics" in source
    assert "get_programme_export_queue_metrics" in source


def test_lag_check_lives_in_the_scheduler_not_the_worker():
    """The worker cannot report its own death."""
    worker = _read("scripts/run_consensus_worker.py")
    assert "CONSENSUS QUEUE STUCK" not in worker
