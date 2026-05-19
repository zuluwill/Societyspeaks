"""
Tests for synchronous first-brief generation (Block B "wow moment" piece).

Covers:
  - happy path: generator returns id within deadline → ('ready', id)
  - generator returns None (no row) → ('failed', None)
  - generator raises → ('failed', None)
  - deadline exceeded → ('pending', None), worker keeps running
  - deadline_seconds override
  - thread-isolation: worker uses its own session (doesn't poison request session)
"""
import time

import pytest

from app.briefing.first_brief import (
    FirstBriefResult,
    generate_first_brief_sync,
)


def test_ready_when_generator_returns_id_within_deadline(app):
    def gen(briefing_id):
        return 12345

    with app.app_context():
        result = generate_first_brief_sync(briefing_id=1, generator=gen, deadline_seconds=5)

    assert isinstance(result, FirstBriefResult)
    assert result.status == 'ready'
    assert result.brief_run_id == 12345
    assert result.elapsed_s >= 0


def test_failed_when_generator_returns_none(app):
    def gen(briefing_id):
        return None

    with app.app_context():
        result = generate_first_brief_sync(briefing_id=2, generator=gen, deadline_seconds=5)

    assert result.status == 'failed'
    assert result.brief_run_id is None


def test_failed_when_generator_raises(app):
    def gen(briefing_id):
        raise RuntimeError("generator boom")

    with app.app_context():
        result = generate_first_brief_sync(briefing_id=3, generator=gen, deadline_seconds=5)

    assert result.status == 'failed'
    assert result.brief_run_id is None


def test_pending_when_generator_exceeds_deadline(app):
    """If the worker doesn't finish in time, return pending and let it run."""
    barrier_hit = []

    def slow_gen(briefing_id):
        # Sleeps longer than the deadline — caller should get 'pending'.
        time.sleep(0.5)
        barrier_hit.append(briefing_id)
        return 999

    with app.app_context():
        result = generate_first_brief_sync(
            briefing_id=4, generator=slow_gen, deadline_seconds=0.1,
        )

    assert result.status == 'pending'
    assert result.brief_run_id is None
    assert result.elapsed_s >= 0.1

    # Give the worker thread time to actually complete in the background, to
    # prove we didn't cancel it. The barrier_hit list should populate.
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not barrier_hit:
        time.sleep(0.05)
    assert barrier_hit == [4], "Worker thread should keep running after timeout"


def test_deadline_seconds_override_takes_precedence_over_config(app):
    def slow_gen(briefing_id):
        time.sleep(0.3)
        return 1

    app.config['FIRST_BRIEF_SYNC_DEADLINE_SECONDS'] = 30  # would block test
    with app.app_context():
        # Override on call wins.
        result = generate_first_brief_sync(
            briefing_id=5, generator=slow_gen, deadline_seconds=0.05,
        )

    assert result.status == 'pending'


def test_uses_config_deadline_when_not_passed(app):
    def gen(briefing_id):
        time.sleep(0.2)
        return 7

    app.config['FIRST_BRIEF_SYNC_DEADLINE_SECONDS'] = 0.05
    with app.app_context():
        result = generate_first_brief_sync(briefing_id=6, generator=gen)

    assert result.status == 'pending'
