"""
Unit tests for app/lib/redis_client.

These guard the contract that all 13+ in-app callers depend on:

  1. ``get_client()`` returns None when ``REDIS_URL`` is unset.
  2. Successive calls with the same arguments return the SAME cached
     client instance — i.e. there is one persistent pool per process.
     Regressing this resurrects the original bug where every Redis
     operation triggered a fresh DNS lookup.
  3. ``decode_responses=True`` and ``decode_responses=False`` produce
     two separately cached clients (call sites depend on both modes).
  4. Pool init failure is NOT cached — the next call retries cleanly.
  5. ``reset_pools_after_fork()`` calls ``pool.reset()`` on every
     cached client and clears the cache.
"""

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _clear_redis_client_cache():
    """Ensure each test starts with an empty client cache.

    The shared client module caches at module level for the lifetime of
    the process, so tests that don't reset would inherit fixtures from
    earlier tests.
    """
    from app.lib import redis_client as rc
    rc.reset_clients()
    yield
    rc.reset_clients()


def test_returns_none_when_redis_url_unset(monkeypatch):
    monkeypatch.delenv('REDIS_URL', raising=False)
    from app.lib.redis_client import get_client
    assert get_client() is None
    assert get_client(decode_responses=False) is None


def test_returns_none_when_redis_url_blank(monkeypatch):
    monkeypatch.setenv('REDIS_URL', '   ')
    from app.lib.redis_client import get_client
    assert get_client() is None


def test_caches_client_per_url_and_decode_flag(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')

    fake_pool = MagicMock()
    fake_pool.max_connections = 50
    fake_client_decoded = MagicMock(name="decoded")
    fake_client_bytes = MagicMock(name="bytes")

    with patch('redis.ConnectionPool.from_url', return_value=fake_pool):
        with patch('redis.Redis', side_effect=[fake_client_decoded, fake_client_bytes]):
            from app.lib.redis_client import get_client

            a = get_client(decode_responses=True)
            b = get_client(decode_responses=True)
            c = get_client(decode_responses=False)
            d = get_client(decode_responses=False)

    assert a is b, "decode_responses=True calls must return the cached instance"
    assert c is d, "decode_responses=False calls must return the cached instance"
    assert a is not c, "decode_responses=True/False must be cached separately"


def test_init_failure_not_cached(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')

    fake_pool = MagicMock()
    fake_pool.max_connections = 50
    fake_client = MagicMock()

    with patch('redis.ConnectionPool.from_url', side_effect=[RuntimeError("boom"), fake_pool]):
        with patch('redis.Redis', return_value=fake_client):
            from app.lib.redis_client import get_client

            first = get_client()
            second = get_client()

    assert first is None, "first call should return None when pool creation fails"
    assert second is fake_client, "second call should retry and succeed"


def test_reset_pools_after_fork_resets_and_clears(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')

    fake_pool = MagicMock()
    fake_pool.max_connections = 50
    fake_client = MagicMock()
    fake_client.connection_pool = fake_pool

    with patch('redis.ConnectionPool.from_url', return_value=fake_pool):
        with patch('redis.Redis', return_value=fake_client):
            from app.lib.redis_client import get_client, reset_pools_after_fork, _clients

            client_before = get_client()
            assert client_before is fake_client
            assert len(_clients) == 1

            count = reset_pools_after_fork()

            assert count == 1
            assert len(_clients) == 0, "cache must be cleared so the next get_client builds fresh"
            fake_pool.reset.assert_called_once()


def test_max_connections_overridable_via_env(monkeypatch):
    monkeypatch.setenv('REDIS_URL', 'redis://localhost:6379/0')
    monkeypatch.setenv('REDIS_SHARED_POOL_MAX_CONNECTIONS', '128')

    captured = {}

    def _fake_from_url(url, **kwargs):
        captured.update(kwargs)
        pool = MagicMock()
        pool.max_connections = kwargs.get('max_connections')
        return pool

    with patch('redis.ConnectionPool.from_url', side_effect=_fake_from_url):
        with patch('redis.Redis', return_value=MagicMock()):
            from app.lib.redis_client import get_client
            get_client()

    assert captured['max_connections'] == 128
