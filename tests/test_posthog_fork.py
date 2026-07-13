"""PostHog lifecycle helpers (fork-safe under gunicorn preload_app)."""

from unittest.mock import MagicMock, patch

from app.lib.posthog_utils import (
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
