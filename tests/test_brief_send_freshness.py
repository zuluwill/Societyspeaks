"""
World-class daily-brief delivery freshness.

Covers the three delivery-correctness fixes:

1. ``DailyBrief.get_latest_published`` — deliver the newest *published* edition,
   never a draft, degrading gracefully when generation is late. Replaces the
   fragile fixed-18:00-UTC cutover in ``send_todays_brief_hourly``.
2. ``DailyBriefSubscriber`` local-day dedup — cap at one send per subscriber
   *local* calendar day (plus per-brief-id idempotency), fixing the UTC-day
   dedup that both double-sends and locks out subscribers whose local day
   diverges from the server's UTC date.
3. ``_generate_brief_title`` — day/date label from the brief's own date, not the
   host wall clock, and absolute ("Wednesday 15 Jul") so it never reads stale.
"""

from datetime import date, datetime, timedelta
from types import SimpleNamespace

from app.models import DailyBrief, DailyBriefSubscriber


def _brief(db, d, *, status='published', brief_type='daily'):
    b = DailyBrief(date=d, brief_type=brief_type, status=status, title=f"Brief {d}")
    db.session.add(b)
    db.session.flush()
    return b


# --------------------------------------------------------------------------
# get_latest_published
# --------------------------------------------------------------------------

def test_get_latest_published_picks_newest_published(db):
    base = date(2026, 7, 14)
    _brief(db, base - timedelta(days=1), status='published')     # older published
    newest = _brief(db, base, status='published')                # newest published
    _brief(db, base + timedelta(days=1), status='ready')         # newer, but a draft
    db.session.commit()

    assert DailyBrief.get_latest_published('daily').id == newest.id


def test_get_latest_published_excludes_drafts(db):
    _brief(db, date(2026, 7, 14), status='ready')
    _brief(db, date(2026, 7, 15), status='draft')
    db.session.commit()
    assert DailyBrief.get_latest_published('daily') is None


def test_get_latest_published_is_type_scoped(db):
    _brief(db, date(2026, 7, 20), status='published', brief_type='weekly')  # newer weekly
    daily = _brief(db, date(2026, 7, 15), status='published', brief_type='daily')
    db.session.commit()
    assert DailyBrief.get_latest_published('daily').id == daily.id


# --------------------------------------------------------------------------
# local-day dedup — the two cross-UTC-midnight cases a UTC-day check gets wrong
# --------------------------------------------------------------------------

def test_local_day_blocks_double_send_across_utc_midnight(db):
    """Two sends in one local evening straddling UTC midnight = same local day
    (block). A naive UTC-date check would see two dates and wrongly allow the 2nd."""
    s = DailyBriefSubscriber(email='ny@t.test', timezone='America/New_York')
    s.last_sent_at = datetime(2026, 7, 15, 23, 30)   # 19:30 EDT, local Jul 15
    db.session.add(s)
    db.session.commit()

    now = datetime(2026, 7, 16, 1, 0)                # 21:00 EDT, still local Jul 15
    assert s.has_received_brief_on_local_day(now) is True
    # A UTC-day check would DISAGREE (Jul 15 vs Jul 16) — that's the bug we fix.
    assert s.last_sent_at.date() != now.date()


def test_local_day_allows_next_local_day_within_one_utc_day(db):
    """Local day advanced but both sends share a UTC date: must be allowed
    (new local day). A naive UTC-date check would wrongly lock the subscriber out."""
    s = DailyBriefSubscriber(email='tokyo@t.test', timezone='Asia/Tokyo')
    s.last_sent_at = datetime(2026, 7, 16, 1, 0)     # 10:00 JST, local Jul 16
    db.session.add(s)
    db.session.commit()

    now = datetime(2026, 7, 16, 23, 0)               # 08:00 JST Jul 17, next local day
    assert s.has_received_brief_on_local_day(now) is False
    # A UTC-day check would AGREE they'd already been sent (both Jul 16) — the lockout.
    assert s.last_sent_at.date() == now.date()


def test_invalid_timezone_falls_back_to_utc(db):
    s = DailyBriefSubscriber(email='bad@t.test', timezone='Not/AZone')
    s.last_sent_at = datetime(2026, 7, 15, 12, 0)
    db.session.add(s)
    db.session.commit()
    # Must not raise; resolves to UTC.
    assert s.has_received_brief_on_local_day(datetime(2026, 7, 15, 23, 0)) is True
    assert s.has_received_brief_on_local_day(datetime(2026, 7, 16, 0, 30)) is False


# --------------------------------------------------------------------------
# can_receive_brief — combines the two guards
# --------------------------------------------------------------------------

def test_can_receive_blocks_same_brief_id(db):
    s = DailyBriefSubscriber(email='dup@t.test', timezone='UTC')
    s.last_brief_id_sent = 42
    s.last_sent_at = datetime(2026, 7, 1, 12, 0)      # weeks ago — local-day won't block
    db.session.add(s)
    db.session.commit()
    assert s.can_receive_brief(brief_id=42) is False   # same edition


def test_can_receive_allows_new_edition_on_new_local_day(db):
    s = DailyBriefSubscriber(email='fresh-edition@t.test', timezone='UTC')
    s.last_brief_id_sent = 42
    s.last_sent_at = datetime(2026, 7, 1, 12, 0)
    db.session.add(s)
    db.session.commit()
    assert s.can_receive_brief(brief_id=99) is True


def test_can_receive_blocks_fresher_edition_same_local_day(db, monkeypatch):
    """One send per local day — even when a newer edition publishes later that evening.

    London BST (UTC+1): at 17:10 UTC (18:10 local) the prior edition is still
    the latest published; at 18:10 UTC today's edition exists but the subscriber
    already received mail on this local day. We do not double-send — the reader
    gets the prior calendar-dated edition honestly labeled, not a second email.
    """
    s = DailyBriefSubscriber(email='london@t.test', timezone='Europe/London')
    s.last_brief_id_sent = 100
    s.last_sent_at = datetime(2026, 7, 15, 17, 10)   # 18:10 BST, prior edition
    db.session.add(s)
    db.session.commit()

    later = datetime(2026, 7, 15, 18, 10)            # 19:10 BST, new edition live
    monkeypatch.setattr('app.models.daily_brief.utcnow_naive', lambda: later)
    assert s.has_received_brief_on_local_day() is True
    assert s.can_receive_brief(brief_id=101) is False  # different edition, same local day


def test_can_receive_blocks_inactive(db):
    s = DailyBriefSubscriber(email='gone@t.test', status='unsubscribed')
    db.session.add(s)
    db.session.commit()
    assert s.can_receive_brief(brief_id=1) is False


def test_never_sent_is_eligible(db):
    s = DailyBriefSubscriber(email='new@t.test')
    db.session.add(s)
    db.session.commit()
    assert s.has_received_brief_on_local_day() is False
    assert s.can_receive_brief(brief_id=1) is True


# --------------------------------------------------------------------------
# title label
# --------------------------------------------------------------------------

def test_title_derives_day_from_brief_date(db):
    from app.brief.generator import BriefGenerator

    gen = BriefGenerator()
    topics = [SimpleNamespace(primary_topic='Politics'),
              SimpleNamespace(primary_topic='Economy')]
    d = date(2026, 7, 15)

    title = gen._generate_brief_title(topics, brief_date=d)

    expected_label = f"{d.strftime('%A')} {d.day} {d.strftime('%b')}"
    assert title.startswith(expected_label + " Brief:"), title
    assert 'Politics' in title and 'Economy' in title


# --------------------------------------------------------------------------
# scheduler send path — end-to-end that send_todays_brief_hourly() selects
# get_latest_published() and skips gracefully with no published edition.
# (Lock and the actual mail send are mocked; subscriber matching is unit-tested
# above via can_receive_brief, so it is stubbed here to isolate orchestration.)
# --------------------------------------------------------------------------

def _mock_send_lock(monkeypatch):
    from app.brief import email_client as ec
    monkeypatch.setattr(ec, 'acquire_daily_send_lock',
                        lambda **kw: (True, None, 'key', 'token', None))
    monkeypatch.setattr(ec, 'release_daily_send_lock', lambda *a, **k: None)


def test_send_hourly_selects_latest_published_edition(db, monkeypatch):
    from app.brief import email_client as ec

    _brief(db, date(2026, 7, 14), status='published')            # older published
    newest = _brief(db, date(2026, 7, 15), status='published')   # newest published
    _brief(db, date(2026, 7, 16), status='ready')                # newer draft — must NOT send
    sub = DailyBriefSubscriber(email='e2e@t.test')
    db.session.add(sub)
    db.session.commit()

    _mock_send_lock(monkeypatch)
    scheduler = ec.BriefEmailScheduler()
    captured = {}
    monkeypatch.setattr(scheduler, 'get_subscribers_for_hour', lambda *a, **k: [sub])
    monkeypatch.setattr(
        scheduler, 'send_to_subscribers',
        lambda subs, brief: (captured.update(brief=brief, n=len(subs))
                             or {'sent': len(subs), 'failed': 0, 'errors': []}),
    )

    result = scheduler.send_todays_brief_hourly()

    assert captured['brief'].id == newest.id     # newest published, never the draft
    assert result['sent'] == 1


def test_send_hourly_skips_when_no_published_edition(db, monkeypatch):
    from app.brief import email_client as ec

    _brief(db, date(2026, 7, 16), status='ready')   # only an unpublished draft exists
    db.session.commit()

    _mock_send_lock(monkeypatch)
    scheduler = ec.BriefEmailScheduler()
    called = {'sent': False}
    monkeypatch.setattr(scheduler, 'send_to_subscribers',
                        lambda *a, **k: called.update(sent=True))

    result = scheduler.send_todays_brief_hourly()

    assert result is None            # graceful skip
    assert called['sent'] is False   # never attempts a send with no published edition


# --------------------------------------------------------------------------
# published_only + public resolver parity
# --------------------------------------------------------------------------

def test_get_by_date_published_only_excludes_ready(db):
    d = date(2026, 7, 16)
    _brief(db, d, status='ready')
    db.session.commit()
    assert DailyBrief.get_by_date(d, published_only=True) is None
    assert DailyBrief.get_by_date(d).status == 'ready'


def test_get_by_date_default_still_allows_ready_for_admin_paths(db):
    d = date(2026, 7, 16)
    ready = _brief(db, d, status='ready')
    db.session.commit()
    assert DailyBrief.get_by_date(d).id == ready.id


def test_brief_today_redirects_to_latest_published_date(app, db):
    d = date(2026, 7, 14)
    _brief(db, d, status='published')
    _brief(db, date(2026, 7, 16), status='ready')   # must not redirect to draft
    db.session.commit()

    client = app.test_client()
    resp = client.get('/brief/today', follow_redirects=False)
    assert resp.status_code == 301
    assert resp.location.endswith('/brief/2026-07-14')


def test_reader_today_redirects_to_latest_published_date(app, db):
    d = date(2026, 7, 14)
    _brief(db, d, status='published')
    db.session.commit()

    client = app.test_client()
    resp = client.get('/brief/today/reader', follow_redirects=False)
    assert resp.status_code == 301
    assert '/brief/2026-07-14/reader' in resp.location


def test_public_view_date_hides_ready_draft(app, db):
    d = date(2026, 7, 16)
    _brief(db, d, status='ready')
    db.session.commit()

    client = app.test_client()
    resp = client.get('/brief/2026-07-16')
    assert resp.status_code == 200
    assert b'No brief available' in resp.data or b'no_brief' in resp.data.lower()


def test_api_latest_returns_latest_published(app, db):
    d = date(2026, 7, 14)
    published = _brief(db, d, status='published')
    _brief(db, date(2026, 7, 16), status='ready')
    sub = DailyBriefSubscriber(email='api@t.test', status='active')
    db.session.add(sub)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['brief_subscriber_id'] = sub.id

    resp = client.get('/api/brief/latest')
    assert resp.status_code == 200
    assert resp.get_json()['id'] == published.id
