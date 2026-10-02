"""Background job queue: claim, retry with backoff, dead-letter, stale recovery."""
from datetime import timedelta

import pytest

from app.lib import job_queue
from app.lib.job_queue import (
    drain_jobs,
    enqueue_job,
    get_queue_metrics,
    is_missing_relation,
    job_handler,
    on_dead_letter,
    process_next_job,
    recover_stale_jobs,
)
from app.lib.time import utcnow_naive
from app.models import BackgroundJob


@pytest.fixture(autouse=True)
def _isolated_registry(monkeypatch):
    monkeypatch.setattr(job_queue, '_HANDLERS', {})
    monkeypatch.setattr(job_queue, '_DEAD_LETTER_HOOKS', {})


def _make_due(job):
    job.run_after = utcnow_naive() - timedelta(seconds=1)
    job_queue.db.session.commit()


def test_a_job_runs_and_stores_its_result(db):
    @job_handler('test.ok')
    def _handler(job):
        return {'echo': job.payload['value']}

    job, created = enqueue_job('test.ok', payload={'value': 7})

    assert created is True
    assert process_next_job() is True
    assert job.status == BackgroundJob.STATUS_COMPLETED
    assert job.result == {'echo': 7}
    assert process_next_job() is False


def test_an_identical_active_job_is_not_queued_twice(db):
    first, created_first = enqueue_job('test.dedupe', dedupe_key='same')
    second, created_second = enqueue_job('test.dedupe', dedupe_key='same')

    assert created_first is True and created_second is False
    assert first.id == second.id
    assert BackgroundJob.query.count() == 1


def test_a_failing_job_is_retried_with_backoff_then_buried(db):
    calls = []
    buried = []

    @job_handler('test.fail')
    def _handler(job):
        calls.append(job.attempts)
        raise RuntimeError('provider down')

    @on_dead_letter('test.fail')
    def _hook(job):
        buried.append(job.id)

    job, _created = enqueue_job('test.fail', max_attempts=3)

    assert process_next_job() is True
    assert job.status == BackgroundJob.STATUS_QUEUED
    assert job.run_after > utcnow_naive(), 'a retry must wait, not spin'
    assert process_next_job() is False, 'not due yet'

    _make_due(job)
    process_next_job()
    _make_due(job)
    process_next_job()

    assert calls == [1, 2, 3]
    assert job.status == BackgroundJob.STATUS_DEAD_LETTER
    assert 'provider down' in job.error_message
    assert buried == [job.id]
    assert get_queue_metrics()['recent_dead_letter_count'] == 1


def test_a_job_with_no_handler_is_buried_not_looped(db):
    job, _created = enqueue_job('test.unknown', max_attempts=1)

    process_next_job()

    assert job.status == BackgroundJob.STATUS_DEAD_LETTER


def test_a_job_whose_worker_died_is_put_back_on_the_queue(db):
    ran = []

    @job_handler('test.stale')
    def _handler(job):
        ran.append(job.id)

    job, _created = enqueue_job('test.stale', timeout_seconds=60)
    job.status = BackgroundJob.STATUS_RUNNING
    job.attempts = 1
    job.started_at = utcnow_naive() - timedelta(seconds=120)
    db.session.commit()

    assert recover_stale_jobs() == 1
    assert job.status == BackgroundJob.STATUS_QUEUED

    _make_due(job)
    assert drain_jobs() == 1
    assert ran == [job.id]
    assert job.status == BackgroundJob.STATUS_COMPLETED


def test_a_delayed_job_waits_for_its_time(db):
    @job_handler('test.delayed')
    def _handler(job):
        return None

    job, _created = enqueue_job('test.delayed', delay_seconds=3600)

    assert process_next_job() is False
    assert get_queue_metrics()['queued_count'] == 0, 'a job that is not due is not lag'
    _make_due(job)
    assert process_next_job() is True


def test_the_database_allows_one_active_job_per_dedupe_key(db):
    from sqlalchemy.exc import IntegrityError

    enqueue_job('test.dedupe', dedupe_key='only-one')
    duplicate = BackgroundJob(kind='test.dedupe', payload={}, dedupe_key='only-one')
    db.session.add(duplicate)

    with pytest.raises(IntegrityError):
        db.session.commit()
    db.session.rollback()

    # Once the first has finished, the same work can be queued again.
    BackgroundJob.query.update({'status': BackgroundJob.STATUS_COMPLETED})
    db.session.commit()
    job, created = enqueue_job('test.dedupe', dedupe_key='only-one')
    assert created is True and job.is_active


def test_a_job_whose_row_is_deleted_while_it_runs_does_not_break_the_worker(db):
    @job_handler('test.vanishes')
    def _handler(job):
        BackgroundJob.query.filter_by(id=job.id).delete()
        db.session.commit()
        return {'done': True}

    enqueue_job('test.vanishes')

    assert process_next_job() is True
    assert BackgroundJob.query.count() == 0


def test_a_missing_table_is_a_migration_gap_not_a_job_failure():
    class _PgError(Exception):
        pgcode = '42P01'

    class _Wrapped(Exception):
        orig = _PgError('relation "background_job" does not exist')

    assert is_missing_relation(_Wrapped()) is True
    assert is_missing_relation(Exception('relation "background_job" does not exist')) is True
    assert is_missing_relation(Exception('no such table: background_job')) is True
    assert is_missing_relation(RuntimeError('boom')) is False


def test_a_failing_job_whose_row_is_deleted_does_not_break_the_worker(db):
    @job_handler('test.vanishes_and_fails')
    def _handler(job):
        BackgroundJob.query.filter_by(id=job.id).delete()
        db.session.commit()
        raise RuntimeError('boom')

    enqueue_job('test.vanishes_and_fails')

    assert process_next_job() is True
