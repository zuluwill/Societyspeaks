"""Regression tests for daily-brief email batch isolation and fallback paths."""

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.brief.email_client import (
    BriefEmailScheduler,
    GMAIL_CLIP_LIMIT_BYTES,
    GMAIL_CLIP_TARGET_BYTES,
    ResendClient,
    _email_html_byte_size,
    _fit_email_html_to_gmail,
    _minify_email_html,
    _strip_email_trim_markers,
)
from app.models import DailyBrief, DailyBriefSubscriber, db


def _bare_client() -> ResendClient:
    client = ResendClient.__new__(ResendClient)
    client._disabled = True
    client.api_key = 'test'
    client.from_email = 'Brief <brief@test.io>'
    client._from_email_addr = 'brief@test.io'
    client.reply_to = 'reply@test.io'
    client.rate_limiter = MagicMock()
    client.last_send_error = None
    return client


@pytest.fixture
def brief_and_subscriber(app, db):
    with app.app_context():
        brief = DailyBrief(
            date=date.today(),
            title='Test Brief',
            intro_text='Intro',
            status='published',
        )
        db.session.add(brief)
        db.session.flush()
        sub = DailyBriefSubscriber(
            email='one@example.com',
            status='active',
            magic_token='magic-one',
        )
        sub2 = DailyBriefSubscriber(
            email='two@example.com',
            status='active',
            magic_token='magic-two',
        )
        db.session.add_all([sub, sub2])
        db.session.commit()
        return brief.id, sub.id, sub2.id


def test_send_brief_resets_stale_last_send_error(app, db, brief_and_subscriber):
    brief_id, _sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        client = _bare_client()
        client.last_send_error = 'stale from subscriber N-1'

        bad_sub = MagicMock()
        bad_sub.id = 99
        bad_sub.email = 'not-an-email'
        ok = client.send_brief(bad_sub, brief)
        assert ok is False
        assert client.last_send_error is None


def test_send_brief_outer_exception_surfaces_error(app, db, brief_and_subscriber):
    brief_id, sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()

        with patch.object(client, '_get_sorted_brief_items', side_effect=RuntimeError('db gone')):
            ok = client.send_brief(sub, brief)
        assert ok is False
        assert 'db gone' in (client.last_send_error or '')


def test_fallback_html_survives_brief_attribute_expiry(app, db, brief_and_subscriber):
    brief_id, _sub_id, _sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        client = _bare_client()
        html = client._fallback_html(
            brief,
            magic_link_url='https://example.com/brief/m/x',
            unsubscribe_url='https://example.com/brief/unsubscribe/x',
        )
        assert 'SOCIETY SPEAKS DAILY BRIEF' in html
        assert f'/brief/{brief.date.isoformat()}' in html


def test_batch_send_continues_after_flush_failure(app, db, brief_and_subscriber):
    brief_id, sub_id, sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        sub2 = db.session.get(DailyBriefSubscriber, sub2_id)

        mock_client = MagicMock()
        mock_client.send_brief.return_value = True

        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        original_commit = db.session.commit
        calls = {'n': 0}

        def flaky_commit():
            calls['n'] += 1
            if calls['n'] == 1:
                raise RuntimeError('connection dropped')
            return original_commit()

        # First claim-commit fails (subscriber 1); the loop must isolate the
        # error and still send to subscriber 2.
        with patch.object(db.session, 'commit', side_effect=flaky_commit):
            results = sched.send_to_subscribers([sub, sub2], brief)

        assert results['sent'] == 1
        assert results['failed'] == 1
        assert mock_client.send_brief.call_count == 1


def test_send_claim_prevents_duplicate_sends(app, db, brief_and_subscriber):
    """Two overlapping send loops (deploy zombie + catch-up run, or a manual
    resume) must produce exactly one send per subscriber: the conditional
    claim on (last_brief_id_sent == brief.id) lets only one loop win.
    Regression for 2026-07-12 (295 duplicated send records)."""
    brief_id, sub_id, sub2_id = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        subs = [db.session.get(DailyBriefSubscriber, sub_id),
                db.session.get(DailyBriefSubscriber, sub2_id)]

        mock_client = MagicMock()
        mock_client.send_brief.return_value = True
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        first = sched.send_to_subscribers(subs, brief)
        second = sched.send_to_subscribers(subs, brief)

        assert first['sent'] == 2
        assert second['sent'] == 0
        assert mock_client.send_brief.call_count == 2


def test_failed_send_releases_claim_for_retry(app, db, brief_and_subscriber):
    """A failed send must not leave the subscriber claimed, or catch-up runs
    would silently skip them forever."""
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)

        mock_client = MagicMock()
        mock_client.send_brief.return_value = False
        mock_client.last_send_error = 'simulated API failure'
        sched = BriefEmailScheduler.__new__(BriefEmailScheduler)
        sched.client = mock_client

        results = sched.send_to_subscribers([sub], brief)
        assert results['failed'] == 1

        db.session.expire_all()
        refreshed = db.session.get(DailyBriefSubscriber, sub_id)
        assert refreshed.last_brief_id_sent is None  # claim released

        mock_client.send_brief.return_value = True
        retry = sched.send_to_subscribers([refreshed], brief)
        assert retry['sent'] == 1


def test_minify_email_html_strips_redundant_inline_sans_font():
    """Redundant inline sans-serif font-family copies are stripped to save bytes.
    Safe because the <head> <style> element rule supplies the same font to every
    client (incl. Outlook). Georgia headline cells keep their own inline font.
    """
    html = (
        '<td style="font-family: -apple-system, BlinkMacSystemFont, '
        "'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; "
        'color: #111;">Hello</td>'
        '<td style="font-family: Georgia, \'Times New Roman\', serif; '
        'font-size: 22px;">Headline</td>'
    )
    out = _minify_email_html(html)
    assert 'sans-serif' not in out            # sans stack stripped
    assert 'Georgia' in out                    # serif headline font preserved
    assert 'Hello' in out and 'Headline' in out


def test_minify_email_html_strips_css_comments():
    """Apple Mail's inbox-snippet generator surfaces prose from CSS /* ... */
    comments in <style> as preview text, ignoring the hidden preheader. The
    minifier must strip CSS comments so they never leak into the inbox snippet.
    """
    html = (
        '<style>body{/* Outlook does not inherit font-family into table '
        'cells, so this element-level rule keeps text correct */'
        'font-family: Arial, sans-serif;}</style>'
        '<td style="color:#111;/* inline note */">Body</td>'
    )
    out = _minify_email_html(html)
    assert 'table cells' not in out            # CSS comment prose gone
    assert 'inline note' not in out            # inline-style comment gone too
    assert 'font-family' in out                # the actual rule survives
    assert 'Body' in out                       # real content untouched


def test_email_head_declares_font_family_for_outlook(app, db, brief_and_subscriber):
    """The rendered email must carry an element-level font-family rule in <style>
    so Outlook (which ignores <body> inheritance) still shows the sans font once
    inline copies are stripped.
    """
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        items = _moderate_items(3)
        with patch.object(client, '_get_sorted_brief_items', return_value=items):
            html = client._render_email(sub, brief, sorted_items=items)
        head = html[:html.find('</style>') + 8]
        assert 'font-family' in head and 'sans-serif' in head


def test_fit_email_html_to_gmail_removes_trim_sections_in_order():
    core = '<p>Core content with stance buttons</p>'
    thankyou = (
        '<!--email-trim:thank-you-->'
        '<p>Thank you message</p>'
        '<!--/email-trim:thank-you-->'
    )
    lens = (
        '<!--email-trim:lens-check-->'
        '<p>Lens check analysis</p>'
        '<!--/email-trim:lens-check-->'
    )
    # Over the limit by just enough that dropping thank-you (first in order) is
    # sufficient; lens-check (last in order) must survive.
    filler = 'x' * (GMAIL_CLIP_TARGET_BYTES - _email_html_byte_size(core + lens))
    html = core + thankyou + lens + filler
    assert _email_html_byte_size(html) > GMAIL_CLIP_TARGET_BYTES

    fitted = _fit_email_html_to_gmail(html, limit=GMAIL_CLIP_TARGET_BYTES)
    assert 'Thank you message' not in fitted
    assert 'Lens check analysis' in fitted
    assert _email_html_byte_size(fitted) <= GMAIL_CLIP_TARGET_BYTES


def test_fit_never_trims_headline_index(app, db, brief_and_subscriber):
    """The headline index is the brief's table of contents and must survive even
    when the email is far over the Gmail limit and story bodies get collapsed.
    """
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        # Deliberately huge: 14 heavy stories, guaranteed to force story collapse.
        items = _moderate_items(14)
        for it in items:
            it.summary_bullets = [f'Bullet {b} ' + ('text ' * 90) for b in range(6)]

        with patch.object(client, '_get_sorted_brief_items', return_value=items):
            html = client._render_email(sub, brief, sorted_items=items)

        # Index survives: every story's headline anchor link is still present.
        assert 'Headlines' in html, 'headline index heading was trimmed'
        for it in items:
            assert f'#item-{it.id}' in html, f'story {it.id} missing from index'
        # And the email still fits.
        assert _email_html_byte_size(html) <= GMAIL_CLIP_TARGET_BYTES
        # Some story bodies were collapsed, so the read-more notice appears.
        assert 'more' in html and 'full brief' in html.lower()


def test_fit_strips_tail_perspectives_before_collapsing_stories():
    """On oversized briefs, shed perspectives from tail stories before dropping
    whole story cards — keeps more inline depth for readers."""
    from app.brief.email_client import GMAIL_CLIP_LIMIT_BYTES, _fit_email_html_to_gmail

    perspectives = (
        '<!--email-trim:story-perspectives-->'
        '<tr><td>Left centre right framing block</td></tr>'
        '<!--/email-trim:story-perspectives-->'
    )
    stories = ''.join(
        f'<tr id="item-{i}"><td>Story {i} body with bullets and sources</td></tr>'
        for i in range(1, 9)
    )
    filler = 'x' * (GMAIL_CLIP_TARGET_BYTES - 500)
    html = stories + perspectives * 8 + filler
    assert _email_html_byte_size(html) > GMAIL_CLIP_TARGET_BYTES

    fitted = _fit_email_html_to_gmail(html, limit=GMAIL_CLIP_TARGET_BYTES)
    assert _email_html_byte_size(fitted) <= GMAIL_CLIP_TARGET_BYTES
    # Perspectives should be stripped from at least one tail story.
    assert fitted.count('Left centre right framing block') < 8


def test_strip_email_trim_markers_removes_marker_comments():
    html = (
        '<!--email-trim:thank-you-->'
        '<p>Keep me</p>'
        '<!--/email-trim:thank-you-->'
    )
    out = _strip_email_trim_markers(html)
    assert 'email-trim' not in out
    assert 'Keep me' in out


def test_render_email_applies_gmail_fit(app, db, brief_and_subscriber):
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()

        heavy_items = []
        for idx in range(12):
            heavy_items.append(
                SimpleNamespace(
                    id=idx + 1,
                    position=idx + 1,
                    headline=f'Heavy headline {idx + 1} ' + ('detail ' * 40),
                    summary_bullets=[f'Bullet {b} ' + ('text ' * 80) for b in range(6)],
                    so_what='Why it matters ' * 60,
                    perspectives={
                        'left': 'Left view ' * 40,
                        'center': 'Centre view ' * 40,
                        'right': 'Right view ' * 40,
                    },
                    source_count=12,
                    coverage_distribution={'left': 0.2, 'center': 0.5, 'right': 0.3},
                    is_underreported=False,
                    section='world_events',
                    depth='full',
                    effective_depth='full',
                    quick_summary=None,
                    trending_topic=None,
                    verification_links=[],
                    blindspot_explanation=None,
                )
            )

        with patch.object(client, '_get_sorted_brief_items', return_value=heavy_items):
            html = client._render_email(sub, brief, sorted_items=heavy_items)

        assert _email_html_byte_size(html) <= GMAIL_CLIP_LIMIT_BYTES
        assert 'Unsubscribe' in html or 'unsubscribe' in html.lower()


def _moderate_items(n):
    """Realistic (not pathological) brief items — a normal daily brief."""
    items = []
    for idx in range(n):
        items.append(
            SimpleNamespace(
                id=idx + 1,
                position=idx + 1,
                headline=f'Story {idx + 1}: a realistic news headline of about ten words',
                summary_bullets=[
                    f'Bullet {b}: a realistic sentence of roughly twenty words '
                    f'summarising a key development for readers to scan quickly now.'
                    for b in range(3)
                ],
                so_what='Why it matters: about forty words of context explaining the '
                        'significance and stakes of this development for the reader here.',
                perspectives={
                    'left': 'Left outlets framed this ' + ('as justice. ' * 6),
                    'center': 'Centre outlets reported ' + ('the facts. ' * 6),
                    'right': 'Right outlets emphasised ' + ('cost. ' * 6),
                },
                source_count=8,
                coverage_distribution={'left': 0.3, 'center': 0.4, 'right': 0.3},
                is_underreported=False,
                section='world_events',
                depth='full',
                effective_depth='full',
                quick_summary=None,
                trending_topic=None,
                verification_links=[],
                blindspot_explanation=None,
            )
        )
    return items


def test_fit_does_not_over_trim_when_minified_email_fits(app, db, brief_and_subscriber):
    """A normal brief that fits under the limit once minified must keep ALL its
    stories. Guards the fit-before-minify regression where the fitter sized the
    ~2.3x-larger un-minified HTML and stripped most stories from every email.
    """
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        items = _moderate_items(6)

        # True minified size with the fitter disabled — the real wire size.
        with patch.object(client, '_get_sorted_brief_items', return_value=items), \
             patch('app.brief.email_client._fit_email_html_to_gmail', side_effect=lambda h, *a, **k: h):
            full = client._render_email(sub, brief, sorted_items=items)
        full_size = _email_html_byte_size(full)
        full_stories = full.count('id="item-')

        # Precondition: this brief genuinely fits once minified.
        assert full_size <= GMAIL_CLIP_TARGET_BYTES, (
            f'test brief too large ({full_size} bytes); lower story count'
        )
        assert full_stories == 6

        # Rendered for real: no trimming should occur.
        with patch.object(client, '_get_sorted_brief_items', return_value=items):
            html = client._render_email(sub, brief, sorted_items=items)

        assert html.count('id="item-') == 6, 'fitter trimmed a brief that already fit'
        assert 'more stories in today' not in html
        assert _email_html_byte_size(html) <= GMAIL_CLIP_TARGET_BYTES


def test_render_email_pins_view_in_browser_to_edition_date(app, db, brief_and_subscriber):
    """View-in-browser must open this edition, not /brief/today."""
    brief_id, sub_id, _ = brief_and_subscriber
    with app.app_context():
        brief = db.session.get(DailyBrief, brief_id)
        sub = db.session.get(DailyBriefSubscriber, sub_id)
        client = _bare_client()
        html = client._render_email(sub, brief, sorted_items=[])
        date_str = brief.date.isoformat()
        assert f'/brief/m/{sub.magic_token}?d={date_str}' in html
        assert f'/brief/{date_str}' in html
        assert 'This edition' in html
        assert '/brief/today' not in html
        assert '/brief/view/' not in html

