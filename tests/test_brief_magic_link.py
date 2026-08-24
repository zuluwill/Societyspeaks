"""Tests for brief magic-link welcome flash behaviour and dated edition links."""

from datetime import date
from types import SimpleNamespace
from urllib.parse import parse_qs, quote, urlparse

from flask import get_flashed_messages

from app.brief.email_client import (
    build_brief_magic_link_url,
    permalink_from_magic_link_url,
    pin_magic_link_to_edition,
    public_brief_url,
)
from app.brief.routes import _flash_brief_magic_link_welcome
from app.briefing.link_tracker import sign_url
from app.models import DailyBrief, DailyBriefSubscriber, DailyQuestion, User


def _seed_brief_user(db, email):
    user = User(email=email, username=email.split('@')[0])
    user.set_password('test-pass-123')
    sub = DailyBriefSubscriber(email=email, status='active', user=user)
    sub.generate_magic_token()
    db.session.add_all([user, sub])
    db.session.commit()
    return sub


def _published_brief(db, d, *, title=None, brief_type='daily'):
    brief = DailyBrief(
        date=d,
        brief_type=brief_type,
        status='published',
        title=title or f'Brief {d}',
    )
    db.session.add(brief)
    db.session.commit()
    return brief


def test_flash_helper_skips_prefetch(app, db):
    with app.app_context():
        db.create_all()
        sub = _seed_brief_user(db, 'prefetch@example.com')
        with app.test_request_context(
            '/brief/m/test',
            headers={'Purpose': 'prefetch', 'User-Agent': 'Mozilla/5.0'},
        ):
            _flash_brief_magic_link_welcome(sub)
            assert get_flashed_messages() == []


def test_flash_helper_queues_welcome_for_human_navigation(app, db):
    with app.app_context():
        db.create_all()
        sub = _seed_brief_user(db, 'human@example.com')
        with app.test_request_context(
            '/brief/m/test',
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh)'},
        ):
            _flash_brief_magic_link_welcome(sub)
            assert get_flashed_messages() == [
                'Welcome back! Signed in as human@example.com'
            ]


def test_layout_dedupes_identical_flash_messages(app, db, client):
    with app.app_context():
        db.create_all()

    with client.session_transaction() as sess:
        sess['_flashes'] = [
            ('success', 'Welcome back! Signed in as duplicate@example.com'),
            ('success', 'Welcome back! Signed in as duplicate@example.com'),
        ]

    resp = client.get('/brief/subscribe', follow_redirects=False)
    assert resp.status_code == 200
    assert resp.data.count(b'Welcome back! Signed in as duplicate@example.com') == 1


def test_build_brief_magic_link_url_pins_daily_date():
    brief = SimpleNamespace(date=date(2026, 8, 10), brief_type='daily')
    url = build_brief_magic_link_url('https://societyspeaks.io', 'tok', brief)
    assert url == 'https://societyspeaks.io/brief/m/tok?d=2026-08-10'


def test_build_brief_magic_link_url_pins_weekly_type():
    brief = SimpleNamespace(date=date(2026, 8, 16), brief_type='weekly')
    url = build_brief_magic_link_url('https://societyspeaks.io/', 'tok', brief)
    assert url == 'https://societyspeaks.io/brief/m/tok?d=2026-08-16&type=weekly'


def test_build_brief_magic_link_url_omits_date_without_brief():
    assert build_brief_magic_link_url(
        'https://societyspeaks.io', 'tok',
    ) == 'https://societyspeaks.io/brief/m/tok'


def test_public_brief_url_is_dated_permalink():
    daily = SimpleNamespace(date=date(2026, 8, 10), brief_type='daily')
    weekly = SimpleNamespace(date=date(2026, 8, 16), brief_type='weekly')
    assert public_brief_url('https://societyspeaks.io', daily) == (
        'https://societyspeaks.io/brief/2026-08-10'
    )
    assert public_brief_url('https://societyspeaks.io/', weekly) == (
        'https://societyspeaks.io/brief/weekly/2026-08-16'
    )


def test_permalink_from_magic_link_url_reads_pinned_date():
    assert permalink_from_magic_link_url(
        'https://societyspeaks.io/brief/m/tok?d=2026-08-10#item-9'
    ) == 'https://societyspeaks.io/brief/2026-08-10'
    assert permalink_from_magic_link_url(
        'https://societyspeaks.io/brief/m/tok?d=2026-08-16&type=weekly'
    ) == 'https://societyspeaks.io/brief/weekly/2026-08-16'
    assert permalink_from_magic_link_url('https://societyspeaks.io/brief/m/tok') is None


def test_pin_magic_link_adds_date_and_keeps_fragment():
    brief = SimpleNamespace(date=date(2026, 8, 10), brief_type='daily')
    pinned = pin_magic_link_to_edition(
        'https://societyspeaks.io/brief/m/tok#item-9', brief,
    )
    parsed = urlparse(pinned)
    assert parse_qs(parsed.query) == {'d': ['2026-08-10']}
    assert parsed.fragment == 'item-9'


def test_pin_magic_link_does_not_override_existing_date():
    brief = SimpleNamespace(date=date(2026, 8, 24), brief_type='daily')
    original = 'https://societyspeaks.io/brief/m/tok?d=2026-08-10'
    assert pin_magic_link_to_edition(original, brief) == original


def test_pin_magic_link_ignores_non_magic_urls():
    brief = SimpleNamespace(date=date(2026, 8, 10), brief_type='daily')
    article = 'https://example.com/story'
    assert pin_magic_link_to_edition(article, brief) == article


def test_magic_link_opens_dated_brief_not_latest(client, db):
    old = date(2026, 8, 10)
    latest = date(2026, 8, 24)
    _published_brief(db, old, title='Kenya-week brief')
    _published_brief(db, latest, title='Today brief')
    sub = _seed_brief_user(db, 'dated@example.com')

    resp = client.get(f'/brief/m/{sub.magic_token}?d=2026-08-10', follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert resp.headers['Location'].endswith('/brief/2026-08-10')
    assert '2026-08-24' not in resp.headers['Location']
    assert 'no-store' in resp.headers.get('Cache-Control', '')


def test_magic_link_without_date_still_opens_today_alias(client, db):
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    sub = _seed_brief_user(db, 'welcome@example.com')

    resp = client.get(f'/brief/m/{sub.magic_token}', follow_redirects=False)
    assert resp.status_code in (302, 303)
    location = resp.headers['Location']
    assert location.endswith('/brief') or location.endswith('/brief/today')


def test_magic_link_weekly_opens_weekly_permalink(client, db):
    week_end = date(2026, 8, 16)
    _published_brief(db, week_end, title='Weekly', brief_type='weekly')
    sub = _seed_brief_user(db, 'weekly@example.com')

    resp = client.get(
        f'/brief/m/{sub.magic_token}?d=2026-08-16&type=weekly',
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    assert resp.headers['Location'].endswith('/brief/weekly/2026-08-16')


def test_magic_link_rejects_non_date_param(client, db):
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    sub = _seed_brief_user(db, 'bad-date@example.com')

    resp = client.get(
        f'/brief/m/{sub.magic_token}?d=https://evil.example',
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    location = resp.headers['Location']
    assert 'evil.example' not in location
    assert location.endswith('/brief') or location.endswith('/brief/today')


def test_view_by_id_redirects_to_dated_permalink(client, db):
    brief = _published_brief(db, date(2026, 8, 10), title='Old')
    resp = client.get(f'/brief/view/{brief.id}', follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/brief/2026-08-10')


def test_view_by_id_weekly_redirects_to_weekly_permalink(client, db):
    brief = _published_brief(db, date(2026, 8, 16), title='Weekly', brief_type='weekly')
    resp = client.get(f'/brief/view/{brief.id}', follow_redirects=False)
    assert resp.status_code == 301
    assert resp.headers['Location'].endswith('/brief/weekly/2026-08-16')


def test_missing_weekly_edition_does_not_show_latest_weekly(client, db):
    _published_brief(db, date(2026, 8, 16), title='Latest weekly', brief_type='weekly')
    resp = client.get('/brief/weekly/2026-08-02', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Latest weekly' not in body


def test_view_by_id_unpublished_does_not_show_latest(client, db):
    draft = DailyBrief(
        date=date(2026, 8, 10),
        brief_type='daily',
        status='draft',
        title='Draft only',
    )
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    db.session.add(draft)
    db.session.commit()
    resp = client.get(f'/brief/view/{draft.id}', follow_redirects=False)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Today brief' not in body


def test_magic_link_follow_through_renders_old_edition_not_latest(client, db):
    _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    sub = _seed_brief_user(db, 'follow@example.com')

    resp = client.get(f'/brief/m/{sub.magic_token}?d=2026-08-10', follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Kenya-week brief' in body
    assert 'Today brief' not in body


def test_dead_magic_token_with_date_still_opens_edition(client, db):
    """Later sends replace the token; old inbox links must still open that day."""
    _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    _published_brief(db, date(2026, 8, 24), title='Today brief')

    resp = client.get('/brief/m/rotated-away-token?d=2026-08-10', follow_redirects=True)
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Kenya-week brief' in body
    assert 'Today brief' not in body
    assert '/subscribe' not in (resp.request.path or '')


def test_dead_magic_token_without_date_still_requires_subscribe(client, db):
    resp = client.get('/brief/m/rotated-away-token', follow_redirects=False)
    assert resp.status_code in (302, 303)
    assert '/brief/subscribe' in resp.headers['Location']


def test_wrap_links_preserves_pinned_date_through_click_tracker(client, app, db):
    from html import unescape
    from app.briefing.link_tracker import wrap_links

    brief = _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    sub = _seed_brief_user(db, 'wrap@example.com')
    magic = build_brief_magic_link_url(
        'https://societyspeaks.io', sub.magic_token, brief,
    )
    html = f'<a href="{magic}">View in your browser</a>'
    wrapped = wrap_links(
        html,
        base_url='https://societyspeaks.io',
        run_id=brief.id,
        r_hash=str(sub.id),
        secret=app.config['SECRET_KEY'],
        track_path='/brief/track/click',
    )
    href = unescape(wrapped.split('href="', 1)[1].split('"', 1)[0])
    parsed = urlparse(href)
    assert parsed.path == f'/brief/track/click/{brief.id}'
    qs = parse_qs(parsed.query)
    assert qs['url'][0] == magic

    track_path = parsed.path + '?' + parsed.query
    resp = client.get(track_path, follow_redirects=False)
    assert resp.status_code in (302, 303)
    location = resp.headers['Location']
    assert location.endswith('/brief/2026-08-10')
    assert 'private' in resp.headers.get('Cache-Control', '')
    assert 'no-store' in resp.headers.get('Cache-Control', '')

    page = client.get('/brief/2026-08-10')
    body = page.get_data(as_text=True)
    assert 'Kenya-week brief' in body
    assert 'Today brief' not in body


def test_track_click_pins_old_unpinned_magic_link(client, app, db):
    brief = _published_brief(db, date(2026, 8, 10), title='Old')
    _published_brief(db, date(2026, 8, 24), title='Today')
    sub = _seed_brief_user(db, 'click@example.com')

    target = 'https://societyspeaks.io/brief/m/old-token#item-4'
    sig = sign_url(brief.id, target, app.config['SECRET_KEY'])
    resp = client.get(
        f'/brief/track/click/{brief.id}'
        f'?url={quote(target, safe="")}&sig={sig}&r={sub.id}',
        follow_redirects=False,
    )
    assert resp.status_code in (302, 303)
    location = resp.headers['Location']
    parsed = urlparse(location)
    assert parsed.path.endswith('/brief/2026-08-10')
    assert parsed.fragment == 'item-4'
    assert 'no-store' in resp.headers.get('Cache-Control', '')


def _anonymous_subscriber(db, email):
    sub = DailyBriefSubscriber(email=email, status='active')
    sub.generate_magic_token()
    db.session.add(sub)
    db.session.commit()
    return sub


def test_magic_link_logs_in_registered_user(client, db):
    _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    sub = _seed_brief_user(db, 'registered@example.com')

    client.get(f'/brief/m/{sub.magic_token}?d=2026-08-10', follow_redirects=True)
    with client.session_transaction() as sess:
        assert sess.get('brief_subscriber_id') == sub.id
        assert sess.get('_user_id') == str(sub.user_id)


def test_magic_link_keeps_anonymous_subscriber_signed_in_without_a_user(client, db):
    _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    sub = _anonymous_subscriber(db, 'anon@example.com')

    client.get(f'/brief/m/{sub.magic_token}?d=2026-08-10', follow_redirects=True)
    with client.session_transaction() as sess:
        assert sess.get('brief_subscriber_id') == sub.id
        assert '_user_id' not in sess


def test_track_click_does_not_hijack_agree_disagree_unsure_votes(client, app, db):
    """Stance buttons are wrapped through click tracking. They must still land
    on the vote confirm page, never the brief permalink."""
    from html import unescape

    from app.briefing.link_tracker import wrap_links

    brief = _published_brief(db, date(2026, 8, 10), title='Kenya-week brief')
    _published_brief(db, date(2026, 8, 24), title='Today brief')
    sub = _anonymous_subscriber(db, 'voter@example.com')
    question = DailyQuestion(
        question_date=date(2026, 8, 10),
        question_number=77,
        question_text='Do vote buttons still work?',
        status='published',
        source_type='discussion',
    )
    db.session.add(question)
    db.session.commit()
    vote_token = sub.generate_vote_token(question.id)

    for choice in ('agree', 'disagree', 'unsure'):
        vote_url = (
            f'https://societyspeaks.io/daily/v/{vote_token}/{choice}'
            f'?source=brief_email'
        )
        html = f'<a href="{vote_url}">{choice}</a>'
        wrapped = wrap_links(
            html,
            base_url='https://societyspeaks.io',
            run_id=brief.id,
            r_hash=str(sub.id),
            secret=app.config['SECRET_KEY'],
            track_path='/brief/track/click',
        )
        href = unescape(wrapped.split('href="', 1)[1].split('"', 1)[0])
        parsed = urlparse(href)
        resp = client.get(
            parsed.path + '?' + parsed.query, follow_redirects=False,
        )
        assert resp.status_code in (302, 303), choice
        location = resp.headers['Location']
        loc = urlparse(location)
        assert loc.path.endswith(f'/daily/v/{vote_token}/{choice}'), choice
        assert parse_qs(loc.query).get('source') == ['brief_email'], choice
        assert '/brief/2026-08-10' not in location
        assert '/brief/2026-08-24' not in location


def test_email_vote_still_records_for_anonymous_subscriber_via_tracker(client, app, db):
    from app.models import DailyQuestionResponse

    brief = _published_brief(db, date.today(), title='Today brief')
    sub = _anonymous_subscriber(db, 'anon-voter@example.com')
    question = DailyQuestion(
        question_date=date.today(),
        question_number=78,
        question_text='Anonymous brief vote?',
        status='published',
        source_type='discussion',
    )
    db.session.add(question)
    db.session.commit()
    vote_token = sub.generate_vote_token(question.id)
    vote_url = (
        f'https://societyspeaks.io/daily/v/{vote_token}/agree?source=brief_email'
    )
    sig = sign_url(brief.id, vote_url, app.config['SECRET_KEY'])
    tracked = client.get(
        f'/brief/track/click/{brief.id}?url={quote(vote_url, safe="")}&sig={sig}&r={sub.id}',
        follow_redirects=False,
    )
    loc = urlparse(tracked.headers['Location'])
    confirm = client.get(loc.path + '?' + loc.query)
    assert confirm.status_code == 200
    with client.session_transaction() as sess:
        assert sess.get('brief_subscriber_id') == sub.id
        assert '_user_id' not in sess

    vote = client.post(
        loc.path + '?' + loc.query, data={}, follow_redirects=False,
    )
    assert vote.status_code == 302
    response = DailyQuestionResponse.query.filter_by(daily_question_id=question.id).one()
    assert response.vote == 1
    assert response.voted_via_email is True


def test_email_vote_logs_in_registered_user(client, db):
    sub = _seed_brief_user(db, 'reg-voter@example.com')
    question = DailyQuestion(
        question_date=date.today(),
        question_number=79,
        question_text='Registered brief vote?',
        status='published',
        source_type='discussion',
    )
    db.session.add(question)
    db.session.commit()
    vote_token = sub.generate_vote_token(question.id)
    client.get(f'/daily/v/{vote_token}/agree?source=brief_email')
    with client.session_transaction() as sess:
        assert sess.get('brief_subscriber_id') == sub.id
        assert sess.get('_user_id') == str(sub.user_id)

