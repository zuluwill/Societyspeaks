"""PostHog lifecycle helpers (fork-safe under gunicorn preload_app)."""

import sys
import types
from unittest.mock import MagicMock, patch

from app.lib.posthog_utils import (
    apply_posthog_gevent_compat,
    configure_posthog_credentials,
    disarm_posthog_blocking_shutdown,
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

    consumer = MagicMock()
    old = MagicMock()
    old.consumers = [consumer]
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "default_client", old, raising=False)
    with patch.object(ph, "setup", create=True) as setup:
        reinitialize_posthog_after_fork()
        old.shutdown.assert_not_called()
        consumer.pause.assert_called_once()
        setup.assert_called_once()


def test_shutdown_server_posthog_does_not_call_sdk_flush_or_shutdown(monkeypatch):
    """flush()/shutdown() join OS threads; under gevent that wedges the hub."""
    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)

    class FakeClient:
        queue = MagicMock(qsize=MagicMock(return_value=0))
        consumers = []

    monkeypatch.setattr(ph, "default_client", FakeClient(), raising=False)

    def boom():
        raise AssertionError("flush/shutdown must not be called from worker_exit")

    monkeypatch.setattr(ph, "flush", boom, raising=False)
    monkeypatch.setattr(ph, "shutdown", boom, raising=False)
    shutdown_server_posthog()
    assert utils._shutdown_done is True


def test_shutdown_drains_queue_then_pauses_consumers(monkeypatch):
    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)
    monkeypatch.setattr(utils, "_gevent_is_patching_threads", lambda: True)

    class FakeQueue:
        def __init__(self):
            self.polls = 0

        def qsize(self):
            self.polls += 1
            return 0 if self.polls >= 3 else 5

    consumer = MagicMock()

    class FakeClient:
        def __init__(self):
            self.queue = FakeQueue()
            self.consumers = [consumer]

    client = FakeClient()
    monkeypatch.setattr(ph, "default_client", client, raising=False)
    monkeypatch.setattr(ph, "flush", MagicMock(side_effect=AssertionError("no flush")))
    monkeypatch.setattr(ph, "shutdown", MagicMock(side_effect=AssertionError("no shutdown")))

    shutdown_server_posthog()
    assert client.queue.polls >= 3
    consumer.pause.assert_called_once()
    consumer.join.assert_not_called()


def test_shutdown_under_gevent_does_not_wait_on_native_join(monkeypatch):
    """Native Thread.join from the hub is the production hang; must return fast."""
    import time

    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)
    monkeypatch.setattr(utils, "_gevent_is_patching_threads", lambda: True)

    consumer = MagicMock()
    consumer.join.side_effect = lambda *a, **k: time.sleep(30)

    class FakeClient:
        queue = MagicMock(qsize=MagicMock(return_value=0))
        consumers = [consumer]

    monkeypatch.setattr(ph, "default_client", FakeClient(), raising=False)

    started = time.monotonic()
    shutdown_server_posthog()
    elapsed = time.monotonic() - started
    assert elapsed < 2.0
    consumer.join.assert_not_called()


def test_shutdown_without_gevent_joins_consumers_with_timeout(monkeypatch):
    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_shutdown_done", False)
    monkeypatch.setattr(ph, "api_key", "phc_test", raising=False)
    monkeypatch.setattr(ph, "project_api_key", "phc_test", raising=False)
    monkeypatch.setattr(utils, "_gevent_is_patching_threads", lambda: False)

    consumer = MagicMock()

    class FakeClient:
        queue = MagicMock(qsize=MagicMock(return_value=0))
        consumers = [consumer]

    monkeypatch.setattr(ph, "default_client", FakeClient(), raising=False)
    shutdown_server_posthog()
    consumer.pause.assert_called_once()
    consumer.join.assert_called()
    timeout = (
        consumer.join.call_args.kwargs.get("timeout")
        if consumer.join.call_args.kwargs
        else None
    )
    if timeout is None and consumer.join.call_args.args:
        timeout = consumer.join.call_args.args[0]
    assert timeout is not None
    assert 0 < float(timeout) <= 1.0


def test_shutdown_server_posthog_source_never_calls_sdk_join_apis():
    """Regression: ph.flush/ph.shutdown from the hub caused Render /health emails."""
    import inspect

    from app.lib import posthog_utils

    src = inspect.getsource(posthog_utils.shutdown_server_posthog)
    body = src.split('"""', 2)[-1]
    assert "ph.flush(" not in body
    assert "ph.shutdown(" not in body
    assert "posthog.flush(" not in body
    assert "posthog.shutdown(" not in body
    assert "_gevent_is_patching_threads" in body
    assert "disarm_posthog_blocking_shutdown" in body


def test_atexit_patch_skips_sdk_client_join():
    """PYTHON-FLASK-JD: Client.__init__ must not land join on the atexit list."""
    import atexit

    from app.lib.posthog_utils import (
        _is_posthog_sdk_join,
        _patch_atexit_skip_posthog_join,
    )

    class _Client:
        def join(self):
            raise AssertionError("sdk join must not be atexit-registered")

    _Client.__module__ = "posthog.client"
    client = _Client()
    assert _is_posthog_sdk_join(client.join) is True

    _patch_atexit_skip_posthog_join()
    before = atexit._ncallbacks()
    atexit.register(client.join)
    assert atexit._ncallbacks() == before

    def _safe():
        return None

    atexit.register(_safe)
    assert atexit._ncallbacks() == before + 1
    atexit.unregister(_safe)


def test_disarm_noops_join_under_gevent(monkeypatch):
    import time

    import posthog as ph
    import app.lib.posthog_utils as utils

    monkeypatch.setattr(utils, "_gevent_is_patching_threads", lambda: True)

    class _Client:
        def join(self):
            time.sleep(30)

    client = _Client()
    monkeypatch.setattr(ph, "default_client", client, raising=False)
    started = time.monotonic()
    disarm_posthog_blocking_shutdown()
    client.join()
    assert time.monotonic() - started < 1.0
    assert getattr(client, "_ss_join_neutered", False) is True


def test_configure_patches_atexit_to_skip_sdk_join(monkeypatch):
    import atexit

    import posthog as ph
    import posthog.client as ph_client

    monkeypatch.setattr(ph, "api_key", None, raising=False)
    monkeypatch.setattr(ph, "project_api_key", None, raising=False)
    monkeypatch.setattr(ph, "host", None, raising=False)
    monkeypatch.setattr(ph, "debug", False, raising=False)

    configure_posthog_credentials("phc_test", "https://eu.i.posthog.com")
    assert getattr(atexit.register, "_ss_skip_posthog_join", False)
    assert getattr(ph_client.Client.__init__, "_ss_gevent_atexit_patched", False)

