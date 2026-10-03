"""PostHog funnel for the consultation product: attribution, the middle steps, revenue."""
import sys
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from app.consultations import billing, jobs
from app.models import ConsultationPlan, User
from tests.test_consultations import _live_consultation, _login, enabled, host  # noqa: F401  (fixtures)

pytestmark = pytest.mark.usefixtures('sqlite_vote_functions')


@pytest.fixture
def events(monkeypatch):
    """Every PostHog capture, from the consultation helper and the identity helper."""
    sent = []

    class _PostHog:
        project_api_key = 'phc_test'

    def _capture(**kwargs):
        sent.append(kwargs)
        return True

    monkeypatch.setitem(sys.modules, 'posthog', _PostHog)
    monkeypatch.setattr('app.lib.posthog_utils.safe_posthog_capture', _capture)
    monkeypatch.setattr('app.lib.identity_analytics.safe_posthog_capture', _capture)
    return sent


def _named(events, name):
    return [e for e in events if e['event'] == name]


@pytest.fixture
def magic_links(monkeypatch):
    links = []
    monkeypatch.setattr(
        'app.lib.magic_login_dispatch.send_magic_login_email',
        lambda user, url, submitted_email=None: links.append(url) or True,
    )
    return links


def test_the_campaign_rides_on_the_sign_in_link(app, enabled, client, magic_links, events):
    client.get('/consultations/self-serve?utm_source=newsletter&utm_medium=email&utm_campaign=launch')
    client.post('/consultations/start', data={'email': 'new.host@example.org'})

    next_url = parse_qs(urlparse(magic_links[0]).query)['next'][0]
    assert next_url.startswith('/consultations/new?')
    assert parse_qs(urlparse(next_url).query) == {
        'utm_source': ['newsletter'], 'utm_medium': ['email'], 'utm_campaign': ['launch'],
    }


def test_a_new_host_is_counted_as_a_sign_up_with_where_they_came_from(app, enabled, client, magic_links, events):
    client.get('/consultations/self-serve?utm_source=newsletter&utm_medium=email')
    client.post('/consultations/start', data={'email': 'new.host@example.org'})

    signed_up = _named(events, 'user_signed_up')[0]
    assert signed_up['properties']['signup_method'] == 'consultation_magic_link'
    assert signed_up['properties']['utm_source'] == 'newsletter'

    first = _named(events, 'consultation_signed_up')[0]['properties']
    assert first['acquisition_source'] == 'newsletter'
    assert first['existing_account'] is False
    assert first['$set_once']['first_consultation_source'] == 'newsletter'


def test_an_existing_account_counts_once_without_a_second_sign_up(app, enabled, client, magic_links, events, db):
    db.session.add(User(username='old', email='old.hand@example.org', password='x', email_verified=True))
    db.session.commit()
    client.post('/consultations/start', data={'email': 'old.hand@example.org'})

    assert not _named(events, 'user_signed_up')
    first = _named(events, 'consultation_signed_up')[0]['properties']
    assert first['existing_account'] is True
    assert first['acquisition_source'] == 'direct'


def test_campaign_values_are_cleaned_before_they_are_stored(app, enabled, client, magic_links, events):
    client.get('/consultations/self-serve?utm_source=jane%40example.org%20%3Cscript%3E')
    client.post('/consultations/start', data={'email': 'new.host@example.org'})
    source = _named(events, 'consultation_signed_up')[0]['properties']['utm_source']
    assert source == 'janeexample.orgscript'


def test_closing_records_who_closed_it_and_the_turnout(app, enabled, host, monkeypatch, events):
    consultation = _live_consultation(host, monkeypatch)
    jobs.close_and_report(consultation, closed_by='host')

    closed = _named(events, 'consultation_closed')[0]
    assert closed['distinct_id'] == str(host.id)
    assert closed['properties']['closed_by'] == 'host'
    assert closed['properties']['participant_count'] == 0
    assert 'question' not in str(closed) and 'surplus' not in str(closed)


def test_sharing_and_the_big_screen_count_once_each(app, enabled, host, client, monkeypatch, events):
    consultation = _live_consultation(host, monkeypatch)
    _login(client, host)
    for _ in range(2):
        client.get(f'/consultations/{consultation.id}/share')
        client.get(f'/consultations/{consultation.id}/present')

    shared = _named(events, 'consultation_shared')
    ids = {e['insert_id'] for e in shared}
    assert {e['properties']['channel'] for e in shared} == {'share_page', 'big_screen'}
    # Each page sends the same insert id every time, so PostHog keeps one of each.
    assert ids == {
        f'consultation_shared:{consultation.id}:share_page',
        f'consultation_shared:{consultation.id}:big_screen',
    }


def test_the_made_with_links_say_where_the_visitor_came_from(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    page = client.get(f'/c/{consultation.access_token}').get_data(as_text=True)
    assert 'utm_source=made_with' in page and 'utm_medium=participant_page' in page


def test_revenue_properties_are_in_pounds_and_pence():
    assert billing._revenue_properties('single', 9900, 'GBP') == {
        'plan': 'single', 'currency': 'GBP', 'amount_pence': 9900, 'revenue': 99.0,
    }
    assert billing._revenue_properties('annual', 0, None) == {'plan': 'annual', 'currency': 'gbp'}


def test_an_annual_renewal_is_recorded_with_its_revenue(app, enabled, host, events, db):
    start = datetime(2026, 10, 3)
    plan = ConsultationPlan(
        user_id=host.id, stripe_subscription_id='sub_1', status='active', current_period_end=start,
    )
    db.session.add(plan)
    db.session.commit()

    renewed = {
        'id': 'sub_1', 'status': 'active', 'cancel_at_period_end': False,
        'current_period_end': int((start + timedelta(days=365)).timestamp()),
        'items': {'data': [{'price': {'unit_amount': 60000, 'currency': 'gbp'}}]},
    }
    billing.sync_plan(renewed, user=host)

    event = _named(events, 'consultation_plan_renewed')[0]
    assert event['properties']['revenue'] == 600.0
    assert event['properties']['plan'] == 'annual'
