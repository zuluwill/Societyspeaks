"""Crash-safety contract for the daily-question batch send.

A deploy/restart mid-run must never re-email subscribers who were already
sent to: markers are committed per batch, each batch carries a stable
Idempotency-Key, and send results map back to the right subscriber even
when some payload builds fail.
"""
from types import SimpleNamespace

import app as app_pkg
import app.resend_client as resend_client
from app.lib.email_analytics import EmailAnalytics


class _BatchClient(resend_client.ResendEmailClient):
    """ResendEmailClient with the network/build edges stubbed out."""

    def __init__(self, batch_size=2):
        # Deliberately skip the real __init__ (env lookups, rate limiter).
        self.BATCH_SIZE = batch_size
        self.batches = []
        self.batch_keys = []
        self.individual_sends = []

    def _build_daily_question_email(self, subscriber, question):
        if getattr(subscriber, 'build_fails', False):
            raise ValueError('render boom')
        return {'to': [subscriber.email]}

    def _send_batch(self, emails, idempotency_key=None):
        self.batches.append(list(emails))
        self.batch_keys.append(idempotency_key)
        failed_indices = [
            i for i, email in enumerate(emails)
            if email['to'][0] in getattr(self, 'reject_emails', ())
        ]
        return {
            'sent': len(emails) - len(failed_indices),
            'failed': len(failed_indices),
            'errors': [f'[{i}] rejected' for i in failed_indices],
            'failed_indices': failed_indices,
        }


class _FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


def _subscriber(sub_id, **extra):
    return SimpleNamespace(
        id=sub_id,
        email=f'sub{sub_id}@example.com',
        last_email_sent=None,
        **extra,
    )


def _question():
    return SimpleNamespace(id=42, question_number=7, topic_category='Civic')


def _run(monkeypatch, client, subscribers):
    session = _FakeSession()
    monkeypatch.setattr(app_pkg, 'db', SimpleNamespace(session=session))
    monkeypatch.setattr(
        EmailAnalytics, 'record_send', staticmethod(lambda **kwargs: None)
    )
    result = client.send_daily_question_batch(subscribers, _question())
    return result, session


def test_markers_committed_once_per_batch(monkeypatch):
    """A crash after batch N must not lose batch N's sent-markers."""
    client = _BatchClient(batch_size=2)
    subscribers = [_subscriber(i) for i in range(1, 6)]  # 5 subs → 3 batches

    result, session = _run(monkeypatch, client, subscribers)

    assert result['sent'] == 5
    assert len(client.batches) == 3
    # One commit per batch — not a single commit at the end of the run.
    assert session.commits == 3
    assert all(s.last_email_sent is not None for s in subscribers)


def test_each_batch_gets_stable_distinct_idempotency_key(monkeypatch):
    client = _BatchClient(batch_size=2)
    subscribers = [_subscriber(i) for i in range(1, 5)]

    _run(monkeypatch, client, subscribers)

    assert all(key and key.startswith('daily-question:42:') for key in client.batch_keys)
    assert len(set(client.batch_keys)) == len(client.batch_keys)

    # Same batch composition → same key (safe for HTTP retries of one call).
    rerun_client = _BatchClient(batch_size=2)
    for sub in subscribers:
        sub.last_email_sent = None
    _run(monkeypatch, rerun_client, subscribers)
    assert rerun_client.batch_keys == client.batch_keys


def test_build_failure_does_not_mark_or_misalign_other_subscribers(monkeypatch):
    """A failed payload build must not shift send results onto the wrong subscriber."""
    client = _BatchClient(batch_size=3)
    good_one = _subscriber(1)
    broken = _subscriber(2, build_fails=True)
    good_two = _subscriber(3)

    result, _ = _run(monkeypatch, client, [good_one, broken, good_two])

    assert result['sent'] == 2
    assert result['failed'] == 1
    assert result['failed_emails'] == [broken.email]
    assert broken.last_email_sent is None
    assert good_one.last_email_sent is not None
    assert good_two.last_email_sent is not None
    # Only the two built emails reached the batch API.
    assert [e['to'] for e in client.batches[0]] == [[good_one.email], [good_two.email]]


def test_partial_batch_failure_only_marks_accepted_recipients(monkeypatch):
    """A recipient Resend rejects must stay unmarked so the next run retries them."""
    client = _BatchClient(batch_size=3)
    accepted = _subscriber(1)
    rejected = _subscriber(2)
    also_accepted = _subscriber(3)
    client.reject_emails = {rejected.email}

    result, _ = _run(monkeypatch, client, [accepted, rejected, also_accepted])

    assert result['sent'] == 2
    assert result['failed'] == 1
    assert rejected.last_email_sent is None
    assert rejected.email in result['failed_emails']
    assert accepted.last_email_sent is not None
    assert also_accepted.last_email_sent is not None


def test_daily_send_query_is_deterministically_ordered():
    """The batch Idempotency-Key fingerprints each subscriber slice, so the
    scheduler's subscriber query must be deterministically ordered — an
    unordered query re-forms different batches on restart and defeats
    Resend's dedup of an already-sent-but-uncommitted batch."""
    import pathlib

    source = pathlib.Path(app_pkg.__file__).with_name('scheduler.py').read_text()
    idx = source.find("email_frequency='daily'")
    assert idx != -1, 'daily subscriber query not found in scheduler.py'
    window = source[idx:idx + 600]
    assert '.order_by(DailyQuestionSubscriber.id)' in window, (
        'daily subscriber query must be ordered by id for stable batch keys'
    )


def test_weekly_and_monthly_digests_carry_stable_idempotency_key(app, monkeypatch):
    """Digest sends must carry a per-recipient X-Entity-Ref-ID so a retried
    5xx or a crash before the caller's commit cannot deliver twice."""
    captured = []

    class _DigestClient(resend_client.ResendEmailClient):
        def __init__(self):
            self.base_url = 'https://example.test'
            self.from_email_daily = 'daily@example.test'

        def _send_with_retry(self, email_data, use_rate_limit=False):
            captured.append(email_data)
            return True

    monkeypatch.setattr(resend_client, '_render_for_user', lambda *a, **k: '<html></html>')
    monkeypatch.setattr(resend_client, '_wrap_links', lambda html, **k: html)
    monkeypatch.setattr(resend_client, '_subject_for_user', lambda sub, text, **k: text)
    import app.daily.utils as daily_utils
    monkeypatch.setattr(daily_utils, 'build_question_email_data', lambda *a, **k: {})

    subscriber = SimpleNamespace(
        id=7,
        email='sub7@example.com',
        magic_token='tok',
        unsubscribe_token='untok',
        preferred_send_hour=9,
        get_send_day_name=lambda: 'Monday',
        last_email_sent=None,
        last_weekly_email_sent=None,
        last_monthly_email_sent=None,
    )
    questions = [SimpleNamespace(id=42, question_text='A question?')]

    client = _DigestClient()
    with app.app_context():
        assert client.send_weekly_questions_digest(subscriber, questions)
        assert client.send_monthly_questions_digest(subscriber, questions)

    from app.lib.time import utcnow_naive
    from app.lib.email_idempotency import content_fingerprint, scoped_entity_ref

    iso_year, iso_week, _ = utcnow_naive().date().isocalendar()
    weekly, monthly = captured
    q_fp = content_fingerprint([42])
    assert weekly['headers']['X-Entity-Ref-ID'] == scoped_entity_ref(
        'weekly-digest', f'{iso_year}w{iso_week:02d}', 7, q_fp
    )
    assert monthly['headers']['X-Entity-Ref-ID'] == scoped_entity_ref(
        'monthly-digest', f'{utcnow_naive():%Y-%m}', 7, q_fp
    )
