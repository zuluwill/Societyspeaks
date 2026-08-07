"""Tests for platform-wide social share copy and encoding."""

from markupsafe import Markup

from app.daily.share_text import (
    build_daily_question_share_text,
    build_daily_results_share_text,
)
from app.lib.share_text import (
    build_brief_share_text,
    build_discussion_share_text,
    build_profile_share_text,
)
from app.lib.share_utils import plain_share_text, share_urlencode

QUESTION = (
    'The US strikes on Iran must be accompanied by a clear strategy '
    'for achieving peace to be effective.'
)


def test_build_daily_results_share_text_uses_literal_quotes(app):
    with app.app_context():
        text = build_daily_results_share_text(
            QUESTION,
            total=102,
            agree=34,
            disagree=33,
            unsure=33,
        )
    assert text.startswith('"')
    assert '&#34;' not in text
    assert '102' in text
    assert '34% agree' in text


def test_build_daily_question_share_text_uses_literal_quotes(app):
    with app.app_context():
        text = build_daily_question_share_text(QUESTION)
    assert text.startswith('"')
    assert '&#34;' not in text
    assert '2 minutes' in text


def test_build_discussion_share_text_includes_participant_count(app):
    with app.app_context():
        text = build_discussion_share_text(
            'Climate adaptation funding',
            participant_count=842,
        )
    assert '842' in text
    assert 'Climate adaptation funding' in text
    assert '&#34;' not in text


def test_build_brief_share_text_daily(app):
    with app.app_context():
        text = build_brief_share_text('Daily Brief — Jul 21', story_count=4)
    assert '4' in text
    assert '5-minute' in text


def test_build_profile_share_text(app):
    with app.app_context():
        individual = build_profile_share_text('Ada Lovelace', is_company=False)
        company = build_profile_share_text('Civic Labs', is_company=True)
    assert 'Ada Lovelace' in individual
    assert 'Civic Labs' in company


def test_share_urlencode_unescapes_html_entities():
    escaped = Markup('&quot;Hello&quot; — vote now')
    assert plain_share_text(escaped) == '"Hello" — vote now'
    assert '%22Hello%22' in share_urlencode(escaped)
    assert '&#34;' not in share_urlencode(escaped)


def test_share_button_macro_encodes_quotes_for_x(app):
    """Regression: Jinja autoescape must not leak &#34; into tweet intent URLs."""
    stats = {'agree': 34, 'disagree': 33, 'unsure': 33, 'total': 102}
    # Request context so static url_for in the macro works without relying on
    # pytest-flask's autouse push (CI used to miss that package).
    with app.test_request_context('/'):
        share_description = build_daily_results_share_text(
            QUESTION,
            total=stats['total'],
            agree=stats['agree'],
            disagree=stats['disagree'],
            unsure=stats['unsure'],
        )
        html = app.jinja_env.from_string(
            '{% from "components/share_button.html" import share_button %}'
            '{{ share_button(title="Daily", url="https://societyspeaks.io/daily/2099-01-01", description=desc) }}'
        ).render(desc=share_description)

    assert '&#34;' not in html
    assert '%22The%20US%20strikes' in html or '%22The+US+strikes' in html
    assert 'x.com/intent/tweet' in html
    assert 'wa.me' in html
    assert 'bsky.app/intent/compose' in html
    assert 'share-native-btn' in html


def test_daily_og_png_route_returns_image(app, client, monkeypatch):
    from datetime import date
    from types import SimpleNamespace

    from app.models import DailyQuestion

    fake_question = SimpleNamespace(
        question_number=193,
        question_text=QUESTION,
        vote_percentages={'agree': 34, 'disagree': 33, 'unsure': 33, 'total': 102},
    )

    monkeypatch.setattr(
        DailyQuestion,
        'get_by_date',
        staticmethod(lambda question_date: fake_question if question_date == date(2099, 2, 1) else None),
    )
    monkeypatch.setattr('app.daily.og_image_service.is_available', lambda: True)
    monkeypatch.setattr(
        'app.daily.og_image_service.render_daily_question_png',
        lambda **kwargs: b'\x89PNG\r\n\x1a\n' + b'test',
    )

    response = client.get('/daily/2099-02-01/og.png')
    assert response.status_code == 200
    assert response.content_type == 'image/png'
    assert response.data.startswith(b'\x89PNG\r\n\x1a\n')
