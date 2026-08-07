"""PostHog lifecycle helpers (fork-safe under gunicorn preload_app)."""

import sys
import types
from unittest.mock import MagicMock, patch

from app.lib.posthog_utils import (
    apply_posthog_gevent_compat,
    configure_posthog_credentials,
    reinitialize_posthog_after_fork,
    shutdown_server_posthog,
)


def test_configure_posthog_credentials_sets_module_fields(monkeypatch):
    import posthog as ph

    monkeypatch.setattr(ph, "api_key", None, raising=False)
    monkeypatch.setattr(ph, "project_api_key", None, raising=False)
    monkeypatch.setattr(ph, "host", None, raising=False)
    monkeypatch.setattr(ph, "debug", False, raising=False)

    configure_posthog_credentials("phc_test", "https://eu.i.posthog.com", debug=True)
    assert ph.api_key == "phc_test"
    assert ph.project_api_key == "phc_test"
    assert ph.host == "https://eu.i.posthog.com"
    assert ph.debug is True


def test_apply_posthog_gevent_compat_noop_without_gevent_patch(monkeypatch):
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_gevent_compat_applied", False)

    class _FakeMonkey:
        @staticmethod
        def is_module_patched(_name):
            return False

    fake_gevent = types.ModuleType("gevent")
    fake_gevent.monkey = _FakeMonkey()
    monkeypatch.setitem(sys.modules, "gevent", fake_gevent)
    assert apply_posthog_gevent_compat() is False


def test_apply_posthog_gevent_compat_rebinds_queue_and_thread(monkeypatch):
    """PostHog >=7.37.6 _DrainSignal needs threading.Queue.mutex/not_empty."""
    import queue
    import threading

    import app.lib.posthog_utils as utils
    import posthog.client as ph_client
    import posthog.consumer as ph_consumer

    real_queue = queue.Queue
    real_thread = threading.Thread

    class _GeventQueue:
        """Minimal stand-in: constructible but lacks threading.Queue privates."""

        pass

    monkeypatch.setattr(ph_client, "Queue", _GeventQueue, raising=False)

    class _FakeMonkey:
        @staticmethod
        def is_module_patched(name):
            return name == "queue"

        @staticmethod
        def get_original(module, name):
            assert module in ("queue", "threading")
            return real_queue if name == "Queue" else real_thread

    fake_gevent = types.ModuleType("gevent")
    fake_gevent.monkey = _FakeMonkey()
    monkeypatch.setitem(sys.modules, "gevent", fake_gevent)
    monkeypatch.setattr(utils, "_gevent_compat_applied", False)

    assert apply_posthog_gevent_compat() is True
    assert ph_client.Queue is real_queue
    assert hasattr(ph_client.Queue(), "mutex")
    assert hasattr(ph_client.Queue(), "not_empty")
    assert ph_consumer.Consumer.__bases__ == (real_thread,)
    assert apply_posthog_gevent_compat() is True


def test_configure_posthog_falls_back_to_sync_mode_when_compat_fails(monkeypatch):
    import posthog as ph
    import app.lib.posthog_utils as utils

    class _FakeMonkey:
        @staticmethod
        def is_module_patched(name):
            return name == "queue"

    fake_gevent = types.ModuleType("gevent")
    fake_gevent.monkey = _FakeMonkey()
    monkeypatch.setitem(sys.modules, "gevent", fake_gevent)
    monkeypatch.setattr(utils, "apply_posthog_gevent_compat", lambda: False)
    monkeypatch.setattr(ph, "sync_mode", False, raising=False)

    configure_posthog_credentials("phc_test", "https://eu.i.posthog.com")
    assert ph.sync_mode is True


def test_reinitialize_posthog_after_fork_noop_without_key(monkeypatch):
    import posthog as ph

    monkeypatch.setattr(ph, "api_key", None, raising=False)
    monkeypatch.setattr(ph, "project_api_key", None, raising=False)
    with patch.object(ph, "setup", create=True) as setup:
        reinitialize_posthog_after_fork()
        setup.assert_not_called()


def test_reinitialize_posthog_after_fork_replaces_default_client(monkeypatch):
    import posthog as ph

    old = MagicMock()
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "default_client", old, raising=False)
    with patch.object(ph, "setup", create=True) as setup:
        reinitialize_posthog_after_fork()
        old.shutdown.assert_called_once()
        setup.assert_called_once()


def test_shutdown_server_posthog_swallows_gevent_queue_attribute_error(monkeypatch):
    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)

    def boom():
        raise AttributeError("'gevent._gevent_cqueue.Queue' object has no attribute 'all_tasks_done'")

    monkeypatch.setattr(ph, "flush", boom, raising=False)
    monkeypatch.setattr(ph, "shutdown", boom, raising=False)
    shutdown_server_posthog()  # must not raise
    assert utils._shutdown_done is True


def test_shutdown_drains_queue_before_flush(monkeypatch):
    """Under gevent, flush() raises — the poll-based drain must have emptied
    the queue first so the swallowed error no longer loses the tail batch."""
    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)

    class FakeQueue:
        def __init__(self):
            self.polls = 0

        def qsize(self):
            # Simulate the consumer thread emptying the queue after a few polls.
            self.polls += 1
            return 0 if self.polls >= 3 else 5

    class FakeClient:
        queue = FakeQueue()

    def boom():
        raise AttributeError("no all_tasks_done")

    monkeypatch.setattr(ph, "default_client", FakeClient(), raising=False)
    monkeypatch.setattr(ph, "flush", boom, raising=False)
    monkeypatch.setattr(ph, "shutdown", boom, raising=False)

    shutdown_server_posthog()  # must not raise
    assert FakeClient.queue.polls >= 3  # drained before flush was attempted
