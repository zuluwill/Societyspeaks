"""Regression tests for extraction-queue transient-error handling.

Guards the production contract fixed after the Neon SSL-abort Sentry: a transient
connectivity drop during extraction must bubble to ``with_db_retry`` (retried on a
fresh connection), never mark the upload 'failed'. The classification is by error
*message* (any transient DBAPIError), not a hardcoded exception-type tuple — so a
pooler blip that surfaces as a plain ``DBAPIError`` is still caught. Non-transient
DB errors and ordinary extraction errors still mark the source failed.
"""

import pytest
from sqlalchemy.exc import DBAPIError

from app import db
from app.models import InputSource
from app.briefing.ingestion import extraction_queue


def _make_upload():
    source = InputSource(
        owner_type='user',
        owner_id=1,
        name='report.pdf',
        type='upload',
        status='extracting',
        storage_key='uploads/report.pdf',
    )
    db.session.add(source)
    db.session.commit()
    return source.id


def _transient_dbapi_error():
    # Not an OperationalError — a bare DBAPIError carrying a transient phrase.
    return DBAPIError('SELECT 1', {}, Exception('SSL SYSCALL error: EOF detected'))


def _permanent_dbapi_error():
    return DBAPIError(
        'UPDATE input_source', {},
        Exception('duplicate key value violates unique constraint'),
    )


def test_transient_db_error_bubbles_and_keeps_source_extracting(app, db, monkeypatch):
    """A transient blip (non-OperationalError type) bubbles; source stays extracting."""
    monkeypatch.setitem(app.config, 'DB_RETRY_ATTEMPTS', 1)  # no retry sleeps in test
    source_id = _make_upload()

    def _boom(_key):
        raise _transient_dbapi_error()

    monkeypatch.setattr(extraction_queue, 'extract_text_from_pdf', _boom)

    with pytest.raises(DBAPIError):
        extraction_queue.process_extraction_queue()

    # with_db_retry discarded the session; re-query on a fresh identity map.
    refreshed = db.session.get(InputSource, source_id)
    assert refreshed.status == 'extracting'   # NOT marked failed on a connectivity drop
    assert refreshed.extraction_error is None


def test_permanent_db_error_marks_source_failed(app, db, monkeypatch):
    """A non-transient DBAPIError is recorded as a failure, not retried forever."""
    source_id = _make_upload()

    def _boom(_key):
        raise _permanent_dbapi_error()

    monkeypatch.setattr(extraction_queue, 'extract_text_from_pdf', _boom)

    extraction_queue.process_extraction_queue()  # handled, does not bubble

    refreshed = db.session.get(InputSource, source_id)
    assert refreshed.status == 'failed'
    assert 'duplicate key' in refreshed.extraction_error


def test_plain_extraction_error_marks_source_failed(app, db, monkeypatch):
    """A non-DB extraction error (e.g. corrupt file) still marks the source failed."""
    source_id = _make_upload()

    def _boom(_key):
        raise ValueError('corrupt PDF header')

    monkeypatch.setattr(extraction_queue, 'extract_text_from_pdf', _boom)

    extraction_queue.process_extraction_queue()

    refreshed = db.session.get(InputSource, source_id)
    assert refreshed.status == 'failed'
    assert 'corrupt PDF' in refreshed.extraction_error


def test_transient_phrase_on_plain_exception_does_not_mark_failed(app, db, monkeypatch):
    """Connectivity phrase on a non-DBAPIError must not mark the upload failed.

    Classification is message-based end-to-end; wrapping layers must not defeat it.
    """
    monkeypatch.setitem(app.config, 'DB_RETRY_ATTEMPTS', 1)
    source_id = _make_upload()

    def _boom(_key):
        raise RuntimeError('could not receive data from server: Software caused connection abort')

    monkeypatch.setattr(extraction_queue, 'extract_text_from_pdf', _boom)

    with pytest.raises(RuntimeError):
        extraction_queue.process_extraction_queue()

    refreshed = db.session.get(InputSource, source_id)
    assert refreshed.status == 'extracting'
    assert refreshed.extraction_error is None
