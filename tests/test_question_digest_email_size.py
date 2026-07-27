"""Question digests must be minified and stay under Gmail's clip threshold.

The daily brief has always run its rendered HTML through ``_minify_email_html``
before send. The question digests did not, and rendered ~66KB for the 5-question
weekly and ~119KB for the 10-question monthly — the monthly was over the ~102KB
point at which Gmail truncates the message body and hides everything after it,
including the visible unsubscribe link, behind "View entire message".

Unlike the brief there is nothing safe to auto-trim (every question is the
payload), so the contract is: always minify, and log loudly if still oversized.
"""

import types

import pytest

from app.brief.email_client import (
    GMAIL_CLIP_LIMIT_BYTES,
    _email_html_byte_size,
    _minify_email_html,
)
from app.resend_client import _compact_digest_html, _render_for_user, _warn_if_clipped


BASE = "https://societyspeaks.io"


def _ns(**kw):
    return types.SimpleNamespace(**kw)


def _question(i):
    """A question with realistic field lengths — short stubs hide size problems."""
    return dict(
        question=_ns(
            id=900 + i,
            question_text=(
                "Should councils be allowed to cap the number of short-term lets "
                "in a given postcode area?"
            ),
            context=(
                "Edinburgh's licensing scheme survived judicial review this month "
                "and three English councils have now written to ministers asking "
                "for equivalent powers under the Levelling Up Act."
            ),
            why_this_question=(
                "Housing supply against property rights splits people who normally "
                "agree with each other."
            ),
        ),
        source_articles=[
            _ns(url=f"{BASE}/o/{i}{j}",
                title="Edinburgh short-term let rules upheld by Court of Session",
                source=_ns(name="The Scotsman"))
            for j in range(2)
        ],
        vote_urls={
            'agree': f"{BASE}/daily/v/t{i}/agree",
            'disagree': f"{BASE}/daily/v/t{i}/disagree",
            'unsure': f"{BASE}/daily/v/t{i}/unsure",
        },
        discussion_stats={
            'has_discussion': True,
            'participant_count': 40 + i,
            'discussion_url': f"{BASE}/d/{i}",
        },
    )


def _render(app, count, *, is_monthly):
    with app.app_context():
        return _render_for_user(
            None,
            'emails/weekly_questions_digest.html',
            questions=[_question(i) for i in range(count)],
            batch_url=f"{BASE}/daily/weekly?token=T",
            preferences_url=f"{BASE}/p",
            unsubscribe_url=f"{BASE}/u",
            send_day_name="Tuesday",
            send_hour=9,
            base_url=BASE,
            is_monthly=is_monthly,
        )


@pytest.mark.parametrize("count,is_monthly", [(5, False), (10, True)])
def test_digest_fits_under_gmail_clip_after_minify(app, count, is_monthly):
    html = _render(app, count, is_monthly=is_monthly)
    with app.app_context():
        compacted = _compact_digest_html(html, 'test digest')

    size = _email_html_byte_size(compacted)
    assert size < GMAIL_CLIP_LIMIT_BYTES, (
        f"{count}-question digest is {size} bytes, over Gmail's "
        f"{GMAIL_CLIP_LIMIT_BYTES}-byte clip threshold"
    )


def test_monthly_digest_was_oversized_before_minify(app):
    """Pins the regression: the unminified 10-question digest exceeds the limit.

    If this ever stops holding the template has shrunk a lot — good, but then the
    minify step is no longer load-bearing and this file should be revisited.
    """
    html = _render(app, 10, is_monthly=True)
    assert _email_html_byte_size(html) > GMAIL_CLIP_LIMIT_BYTES


def test_minify_preserves_every_vote_and_unsubscribe_link(app):
    """Compaction is cosmetic — no URL may be lost."""
    html = _render(app, 5, is_monthly=False)
    with app.app_context():
        compacted = _compact_digest_html(html, 'test digest')

    for i in range(5):
        for choice in ('agree', 'disagree', 'unsure'):
            assert f"{BASE}/daily/v/t{i}/{choice}" in compacted
    assert f"{BASE}/u" in compacted          # unsubscribe
    assert f"{BASE}/p" in compacted          # preferences
    assert "daily/weekly?token=T" in compacted  # batch CTA


def test_minify_preserves_question_text(app):
    html = _render(app, 5, is_monthly=False)
    with app.app_context():
        compacted = _compact_digest_html(html, 'test digest')
    assert "short-term lets" in compacted
    assert "Levelling Up Act" in compacted


def test_compact_returns_unminified_html_when_minify_raises(app, monkeypatch):
    """A cosmetic step must never block a send."""
    html = _render(app, 5, is_monthly=False)

    def boom(_):
        raise RuntimeError('minifier exploded')

    monkeypatch.setattr('app.brief.email_client._minify_email_html', boom)
    with app.app_context():
        assert _compact_digest_html(html, 'test digest') == html


def test_warn_if_clipped_logs_when_oversized(app, caplog):
    oversized = "<html><body>" + ("x" * (GMAIL_CLIP_LIMIT_BYTES + 1)) + "</body></html>"
    with app.app_context():
        with caplog.at_level('WARNING'):
            _warn_if_clipped(oversized, 'Monthly questions digest')
    assert any('Gmail clips' in r.message for r in caplog.records)


def test_warn_if_clipped_silent_when_within_budget(app, caplog):
    with app.app_context():
        with caplog.at_level('WARNING'):
            _warn_if_clipped("<html><body>small</body></html>", 'Weekly questions digest')
    assert not [r for r in caplog.records if 'Gmail clips' in r.message]
