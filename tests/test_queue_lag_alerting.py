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

    unique = f'{utcnow_naive().timestamp()}-{age_seconds}-{id(db)}'
    title = f'Queue Lag Discussion {unique}'
    discussion = Discussion(
        title=title,
        slug=generate_slug(title)[:150],
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


def test_historical_dead_letters_do_not_page_when_recent_count_is_zero():
    """All-time dead_letter_count would re-alert forever; recent_ is the page."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 0,
        'queue_lag_seconds': 0,
        'dead_letter_count': 5,
        'recent_dead_letter_count': 0,
    }
    assert build_queue_lag_alerts('CONSENSUS', metrics, 120) == []


def test_recent_dead_letter_pages_even_when_all_time_is_also_set():
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 0,
        'queue_lag_seconds': 0,
        'dead_letter_count': 5,
        'recent_dead_letter_count': 1,
    }
    alerts = build_queue_lag_alerts('CONSENSUS', metrics, 120)
    assert len(alerts) == 1
    assert '1 job(s)' in alerts[0]


def test_queue_metrics_recent_dead_letter_ignores_old_rows(db):
    from app.discussions.jobs import get_consensus_queue_metrics
    from app.models import ConsensusJob

    old = _queued_consensus_job(db, age_seconds=60)
    old.status = ConsensusJob.STATUS_DEAD_LETTER
    old.completed_at = utcnow_naive() - timedelta(days=30)
    db.session.commit()

    metrics = get_consensus_queue_metrics()
    assert metrics['dead_letter_count'] == 1
    assert metrics['recent_dead_letter_count'] == 0

    recent = _queued_consensus_job(db, age_seconds=60)
    recent.status = ConsensusJob.STATUS_DEAD_LETTER
    recent.completed_at = utcnow_naive() - timedelta(hours=1)
    db.session.commit()

    metrics = get_consensus_queue_metrics()
    assert metrics['dead_letter_count'] == 2
    assert metrics['recent_dead_letter_count'] == 1


def test_idle_dead_worker_does_not_page():
    """No unfinished work means nobody is waiting; do not page on an idle outage."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 0,
        'running_count': 0,
        'queue_lag_seconds': 0,
        'dead_letter_count': 0,
    }
    assert build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=False
    ) == []


def test_heartbeat_probe_none_when_redis_unconfigured(monkeypatch):
    from app.scheduler import _consensus_worker_heartbeat_ok

    monkeypatch.setattr(
        'app.lib.redis_client.get_client', lambda decode_responses=True: None
    )
    assert _consensus_worker_heartbeat_ok() is None


def test_heartbeat_probe_false_when_key_missing(monkeypatch):
    from app.scheduler import _consensus_worker_heartbeat_ok

    class _Fake:
        def get(self, key):
            return None

    monkeypatch.setattr(
        'app.lib.redis_client.get_client', lambda decode_responses=True: _Fake()
    )
    assert _consensus_worker_heartbeat_ok() is False


def test_heartbeat_probe_true_when_key_present(monkeypatch):
    from app.scheduler import _consensus_worker_heartbeat_ok

    class _Fake:
        def get(self, key):
            assert key == 'consensus_worker:last_heartbeat_at'
            return '1710000000'

    monkeypatch.setattr(
        'app.lib.redis_client.get_client', lambda decode_responses=True: _Fake()
    )
    assert _consensus_worker_heartbeat_ok() is True
    """Queued-lag misses a crash mid-job: running_count is 1, queued is 0."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 0,
        'running_count': 1,
        'queue_lag_seconds': 0,
        'dead_letter_count': 0,
    }
    assert build_queue_lag_alerts('CONSENSUS', metrics, 120) == []
    assert build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=True
    ) == []
    assert build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=None
    ) == []

    alerts = build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=False
    )
    assert len(alerts) == 1
    assert 'WORKER UNRESPONSIVE' in alerts[0]
    assert 'societyspeaks-consensus-worker' in alerts[0]


def test_dead_worker_does_not_double_page_stuck_and_unresponsive():
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 2,
        'running_count': 0,
        'queue_lag_seconds': 600,
        'dead_letter_count': 0,
    }
    alerts = build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=False
    )
    assert len(alerts) == 1
    assert 'WORKER UNRESPONSIVE' in alerts[0]
    assert not any('QUEUE STUCK' in a for a in alerts)


def test_live_worker_with_a_backlog_still_pages_stuck_queue():
    """Heartbeat present means the worker is alive; lag is a capacity issue."""
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 2,
        'running_count': 1,
        'queue_lag_seconds': 600,
        'dead_letter_count': 0,
    }
    alerts = build_queue_lag_alerts(
        'CONSENSUS', metrics, 120, heartbeat_ok=True
    )
    assert len(alerts) == 1
    assert 'QUEUE STUCK' in alerts[0]


def test_stale_jobs_page_and_zero_does_not():
    from app.scheduler import build_stale_job_alerts

    assert build_stale_job_alerts('CONSENSUS', 0) == []
    alerts = build_stale_job_alerts('CONSENSUS', 2)
    assert len(alerts) == 1
    assert 'CONSENSUS JOBS STALE' in alerts[0]
    assert '2 timed out' in alerts[0]


def test_malformed_metrics_do_not_raise():
    from app.scheduler import build_queue_lag_alerts

    assert build_queue_lag_alerts('CONSENSUS', {}, 120) == []
    assert build_queue_lag_alerts(
        'CONSENSUS',
        {'queued_count': 'nope', 'queue_lag_seconds': None},
        'bad',
    ) == []


def test_stuck_and_dead_letter_can_page_together():
    from app.scheduler import build_queue_lag_alerts

    metrics = {
        'queued_count': 1,
        'queue_lag_seconds': 600,
        'dead_letter_count': 2,
    }
    alerts = build_queue_lag_alerts('CONSENSUS', metrics, 120)
    assert len(alerts) == 2
    assert any('QUEUE STUCK' in a for a in alerts)
    assert any('DEAD LETTER' in a for a in alerts)


def test_export_threshold_is_independent_of_consensus():
    from app.scheduler import build_queue_lag_alerts

    metrics = {'queued_count': 1, 'queue_lag_seconds': 200, 'dead_letter_count': 0}
    assert build_queue_lag_alerts('PROGRAMME EXPORT', metrics, 300) == []
    alerts = build_queue_lag_alerts('PROGRAMME EXPORT', metrics, 120)
    assert len(alerts) == 1
    assert 'PROGRAMME EXPORT QUEUE STUCK' in alerts[0]


def test_both_queues_are_wired_into_the_scheduler_sweeps():
    source = _read("app/scheduler.py")
    assert "build_queue_lag_alerts(" in source
    assert "'CONSENSUS'" in source
    assert "'PROGRAMME EXPORT'" in source
    assert "build_stale_job_alerts('CONSENSUS'" in source
    assert "build_stale_job_alerts('PROGRAMME EXPORT'" in source
    assert "get_consensus_queue_metrics" in source
    assert "get_programme_export_queue_metrics" in source
    assert source.count("heartbeat_ok=_consensus_worker_heartbeat_ok()") == 2
    assert source.count("build_stale_job_alerts('CONSENSUS'") == 1
    assert source.count("build_stale_job_alerts('PROGRAMME EXPORT'") == 1


def test_lag_check_lives_in_the_scheduler_not_the_worker():
    """The worker cannot report its own death."""
    worker = _read("scripts/run_consensus_worker.py")
    assert "CONSENSUS QUEUE STUCK" not in worker
    assert "WORKER UNRESPONSIVE" not in worker
