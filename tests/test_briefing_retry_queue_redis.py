"""Retry-queue Redis blips must warn and continue, not raise."""

import logging
from unittest.mock import MagicMock

from redis.exceptions import ConnectionError as RedisConnectionError


def test_process_retry_queue_warns_on_redis_connection_closed(monkeypatch, caplog):
    from app.briefing import jobs

    client = MagicMock()
    client.zrangebyscore.side_effect = RedisConnectionError("Connection closed by server.")
    monkeypatch.setattr(jobs, "get_redis_client", lambda: client)

    with caplog.at_level(logging.WARNING, logger="app.briefing.jobs"):
        moved = jobs._process_retry_queue()

    assert moved == 0
    assert any(
        "Transient Redis error processing retry queue" in r.message
        for r in caplog.records
    )
    assert not any(
        r.levelno >= logging.ERROR and "Failed to process retry queue" in r.message
        for r in caplog.records
    )
