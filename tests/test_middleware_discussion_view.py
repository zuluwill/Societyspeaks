"""Best-effort discussion view tracking must survive Neon SSL blips."""

from pathlib import Path
from unittest.mock import patch

from sqlalchemy.exc import OperationalError

from app.middleware import _record_discussion_view
from app.models import Discussion, DiscussionView, generate_slug

_INIT_SRC = Path(__file__).resolve().parents[1] / "app" / "__init__.py"


def _ssl_mac_error():
    return OperationalError(
        "INSERT INTO discussion_view ...",
        {},
        Exception("SSL error: decryption failed or bad record mac"),
    )


def _make_discussion(db):
    discussion = Discussion(
        title="SSL retry discussion",
        slug=generate_slug("SSL retry discussion"),
        has_native_statements=True,
        topic="Society",
        geographic_scope="global",
    )
    db.session.add(discussion)
    db.session.commit()
    return discussion.id


def test_record_discussion_view_retries_after_ssl_mac_error(app, db):
    discussion_id = _make_discussion(db)
    real_commit = db.session.commit
    calls = {"n": 0}

    def flaky_commit():
        calls["n"] += 1
        if calls["n"] == 1:
            raise _ssl_mac_error()
        return real_commit()

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        with patch("app.middleware.db.session.commit", side_effect=flaky_commit):
            with patch("app.middleware.record_event") as record_event:
                with patch("app.middleware.time.sleep"):
                    _record_discussion_view(discussion_id, max_attempts=2, backoff_s=0)

    assert calls["n"] == 2
    assert DiscussionView.query.filter_by(discussion_id=discussion_id).count() == 1
    record_event.assert_called_once()


def test_record_discussion_view_logs_warning_when_transient_exhausted(app, db, caplog):
    discussion_id = _make_discussion(db)

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        with patch("app.middleware.db.session.commit", side_effect=_ssl_mac_error()):
            with patch("app.middleware.time.sleep"):
                with caplog.at_level("WARNING"):
                    _record_discussion_view(discussion_id, max_attempts=2, backoff_s=0)

    assert DiscussionView.query.filter_by(discussion_id=discussion_id).count() == 0
    assert any(
        "Transient DB error in track_discussion_view" in r.getMessage()
        for r in caplog.records
    )
    assert not any(
        "Failed to track discussion view" in r.getMessage() and r.levelname == "ERROR"
        for r in caplog.records
    )


def test_record_discussion_view_logs_error_for_non_transient_failure(app, db, caplog):
    discussion_id = _make_discussion(db)
    permanent = OperationalError(
        "INSERT INTO discussion_view ...",
        {},
        Exception('password authentication failed for user "x"'),
    )

    with app.test_request_context("/", environ_base={"REMOTE_ADDR": "1.2.3.4"}):
        with patch("app.middleware.db.session.commit", side_effect=permanent):
            with caplog.at_level("ERROR"):
                _record_discussion_view(discussion_id, max_attempts=2, backoff_s=0)

    assert any(
        "Failed to track discussion view" in r.getMessage() for r in caplog.records
    )


def test_sentry_before_send_filters_transient_db_phrases_on_log_records():
    """Production 2026-08-06: inlined SSL phrase in ERROR logs bypassed exception filters.

    Phrases live in ``TRANSIENT_DB_ERROR_PHRASES`` (single source of truth).
    ``before_send`` must keep using that tuple for log-record drops — do not
    re-inline the strings in ``app/__init__.py``.
    """
    init_src = _INIT_SRC.read_text(encoding="utf-8")
    phrases_src = (
        Path(__file__).resolve().parents[1] / "app" / "lib" / "db_transient_errors.py"
    ).read_text(encoding="utf-8")
    log_block_start = init_src.index('if "log_record" in hint:')
    exc_block_start = init_src.index('exc_info = hint.get("exc_info")', log_block_start)
    log_block = init_src[log_block_start:exc_block_start]
    assert "drop_if(msg.lower(), *_TRANSIENT_DB_SENTRY_PHRASES)" in log_block
    assert "TRANSIENT_DB_ERROR_PHRASES" in init_src
    assert '"bad record mac"' in phrases_src
    assert '"decryption failed"' in phrases_src
