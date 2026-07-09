"""Tests for app/lib/session_policy.py — anonymous/bot session storage policy.

Guards the fix for Redis filling up with 7-day crawler sessions: anonymous
sessions get a short storage TTL, bot requests store nothing, authenticated
sessions keep the full PERMANENT_SESSION_LIFETIME.
"""
from datetime import timedelta
from unittest.mock import Mock

import pytest
from redis import Redis

from app.lib.session_policy import (
    BOT_UA_INDICATORS,
    SESSION_SKIP_UA_INDICATORS,
    PolicyRedisSessionInterface,
    session_is_authenticated,
    user_agent_is_bot,
)

CHROME_UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/126.0 Safari/537.36')
GOOGLEBOT_UA = 'Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)'


@pytest.fixture
def interface(app):
    client = Mock(spec=Redis)
    iface = PolicyRedisSessionInterface(
        app=app, client=client, key_prefix='session:',
        use_signer=False, permanent=True, sid_length=32,
    )
    return iface, client


def make_session(iface, data):
    session = iface.session_class(data, sid='testsid123')
    session.modified = True
    return session


def test_user_agent_is_bot_matches_and_rejects():
    assert user_agent_is_bot(GOOGLEBOT_UA)
    assert user_agent_is_bot('AhrefsBot/7.0')
    assert not user_agent_is_bot(CHROME_UA)
    assert not user_agent_is_bot(None)
    # extended list catches scripted clients without affecting vote blocking
    assert user_agent_is_bot('python-requests/2.32', SESSION_SKIP_UA_INDICATORS)
    assert not user_agent_is_bot('python-requests/2.32', BOT_UA_INDICATORS)


def test_session_is_authenticated():
    assert session_is_authenticated({'_user_id': '7'})
    assert session_is_authenticated({'partner_portal_id': 3})
    assert not session_is_authenticated({'csrf_token': 'x', 'lang': 'en'})


def test_anonymous_session_gets_short_ttl(app, interface):
    iface, client = interface
    session = make_session(iface, {'csrf_token': 'x'})
    with app.test_request_context(headers={'User-Agent': CHROME_UA}):
        iface._upsert_session(app.permanent_session_lifetime, session, 'session:testsid123')
    assert client.set.called
    expected = int(app.config['ANONYMOUS_SESSION_LIFETIME'].total_seconds())
    assert client.set.call_args.kwargs['ex'] == expected


def test_authenticated_session_keeps_full_lifetime(app, interface):
    iface, client = interface
    session = make_session(iface, {'_user_id': '7', 'csrf_token': 'x'})
    with app.test_request_context(headers={'User-Agent': CHROME_UA}):
        iface._upsert_session(app.permanent_session_lifetime, session, 'session:testsid123')
    assert client.set.call_args.kwargs['ex'] == int(app.permanent_session_lifetime.total_seconds())


def test_bot_anonymous_session_not_stored(app, interface):
    iface, _client = interface
    session = make_session(iface, {'csrf_token': 'x'})
    with app.test_request_context(headers={'User-Agent': GOOGLEBOT_UA}):
        assert iface.should_set_storage(app, session) is False


def test_bot_with_authenticated_session_is_stored(app, interface):
    iface, _client = interface
    session = make_session(iface, {'_user_id': '7'})
    with app.test_request_context(headers={'User-Agent': GOOGLEBOT_UA}):
        assert iface.should_set_storage(app, session) is True


def test_human_anonymous_session_is_stored(app, interface):
    iface, _client = interface
    session = make_session(iface, {'csrf_token': 'x'})
    with app.test_request_context(headers={'User-Agent': CHROME_UA}):
        assert iface.should_set_storage(app, session) is True


def test_anonymous_lifetime_configured_shorter_than_permanent(app):
    anon = app.config['ANONYMOUS_SESSION_LIFETIME']
    assert isinstance(anon, timedelta)
    assert anon <= timedelta(hours=48)
