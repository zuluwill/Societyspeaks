"""The heartbeat must mean "process alive", not "process between jobs".

The scheduler pages CONSENSUS WORKER UNRESPONSIVE when the Redis heartbeat key
is gone and there is unfinished work. Consensus jobs carry a 900s timeout and
an explicit oversize mode for large discussions, so a heartbeat published only
at the top of the work loop expires during a healthy long run — paging a crash
that did not happen, at exactly the moment the product succeeds and discussions
get big enough to cluster slowly.

A false page is worse than no page: it trains you to ignore the alert.
"""

import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_heartbeat_survives_a_missed_tick():
    """Losing one beat must not expire the key, or restarts would flap."""
    from app.lib.process_heartbeat import (
        HEARTBEAT_TTL_SECONDS,
        HEARTBEAT_INTERVAL_SECONDS,
    )

    assert HEARTBEAT_INTERVAL_SECONDS * 2 < HEARTBEAT_TTL_SECONDS, (
        "the beat interval must leave room for at least one missed tick "
        "inside the TTL the scheduler alerts on"
    )


def test_heartbeat_ttl_shorter_than_scheduler_sweep():
    """The scheduler only looks every 5 minutes; the TTL must not be so long
    that a real crash goes unnoticed for multiple sweeps."""
    from app.lib.process_heartbeat import HEARTBEAT_TTL_SECONDS

    scheduler_sweep_seconds = 300
    assert HEARTBEAT_TTL_SECONDS < scheduler_sweep_seconds


def test_heartbeat_keeps_beating_through_a_long_job():
    """The regression this file exists for.

    Simulates a job that blocks far longer than the TTL and asserts the beat
    continues. A heartbeat published from the work loop would produce exactly
    one beat here and then expire.
    """
    from app.lib.process_heartbeat import run_heartbeat_loop

    beats = []
    stop = threading.Event()

    thread = threading.Thread(
        target=run_heartbeat_loop,
        args=(lambda: beats.append(1), stop),
        kwargs={"interval": 0.01},
        daemon=True,
    )
    thread.start()
    try:
        # Stand in for a long clustering run occupying the main thread.
        threading.Event().wait(0.2)
    finally:
        stop.set()
        thread.join(timeout=2)

    assert not thread.is_alive()
    assert len(beats) > 2, (
        f"heartbeat stopped during a long job (only {len(beats)} beat(s)) — "
        f"the scheduler would page a false CONSENSUS WORKER UNRESPONSIVE"
    )


def test_publish_failure_does_not_kill_the_heartbeat_thread():
    """Redis blipping must not silently end liveness reporting for good."""
    from app.lib.process_heartbeat import run_heartbeat_loop

    calls = []
    stop = threading.Event()

    def flaky():
        calls.append(1)
        if len(calls) >= 3:
            stop.set()
        raise RuntimeError("redis down")

    run_heartbeat_loop(flaky, stop, interval=0.001)
    assert len(calls) >= 3


def test_stop_event_ends_the_loop_promptly():
    from app.lib.process_heartbeat import run_heartbeat_loop

    stop = threading.Event()
    stop.set()
    calls = []
    run_heartbeat_loop(lambda: calls.append(1), stop, interval=999)
    assert calls == []


def test_liveness_helpers_do_not_set_worker_env(monkeypatch):
    """Importing cadence helpers must not mark this process as the worker.

    scripts/run_consensus_worker.py setdefaults CONSENSUS_WORKER_PROCESS at
    import; tests that only need the beat loop must not pay that side effect,
    or later tests would run clustering they expected to skip.
    """
    import os
    import sys

    monkeypatch.delenv("CONSENSUS_WORKER_PROCESS", raising=False)
    monkeypatch.delenv("DISABLE_SCHEDULER", raising=False)
    sys.modules.pop("app.lib.process_heartbeat", None)

    from app.lib.process_heartbeat import run_heartbeat_loop  # noqa: F401

    assert os.getenv("CONSENSUS_WORKER_PROCESS") is None
    assert os.getenv("DISABLE_SCHEDULER") is None


def test_work_loop_no_longer_owns_the_heartbeat():
    """Pins the fix: the beat is started once, not published per iteration."""
    source = _read("scripts/run_consensus_worker.py")

    assert "_start_heartbeat_thread(worker_id" in source
    work_loop = source.split("while _RUNNING:", 1)[1]
    assert "_publish_heartbeat(" not in work_loop, (
        "the work loop must not own the heartbeat — a long job would block it"
    )
