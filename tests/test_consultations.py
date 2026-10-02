"""Self-serve consultations: the host journey, the participant page and the privacy rules."""
import hashlib
import json
import secrets

import pytest
from flask import g

from app.consultations import billing, jobs, service
from app.lib.job_queue import drain_jobs
from app.lib.time import utcnow_naive
from app.models import (
    BackgroundJob,
    Consultation,
    ConsultationPurchase,
    ConsultationReport,
    Discussion,
    ModStatus,
    Statement,
    StatementVote,
    User,
)

pytestmark = pytest.mark.usefixtures('sqlite_vote_functions')

DRAFTED = [
    {'content': 'We should spend the surplus on lower fees for members.', 'stance': 'supportive'},
    {'content': 'The surplus should stay in reserves until the lease is renewed.', 'stance': 'critical'},
    {'content': 'Members should vote on any spending above ten thousand pounds.', 'stance': 'exploratory'},
    {'content': 'We should hire a part-time coordinator with the surplus.', 'stance': 'supportive'},
    {'content': 'Spending the surplus now would leave us exposed next year.', 'stance': 'critical'},
    {'content': 'A small grant fund for member projects would be money well spent.', 'stance': 'supportive'},
]


@pytest.fixture
def enabled(app, db, monkeypatch):
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = True
    sent = []
    monkeypatch.setattr(
        'app.consultations.emails._send',
        lambda consultation, **kwargs: sent.append(kwargs['subject']) or True,
    )
    return sent


@pytest.fixture
def host(db):
    user = User(username='host', email='host@example.org', password='x', email_verified=True)
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True
    # The ``db`` fixture keeps one app context open, so Flask-Login's cached
    # user would otherwise carry over between clients.
    g.pop('_login_user', None)


def _mock_llm(monkeypatch, *, drafted=None, narrative=None, screening=None, fail=None):
    from app.lib.llm_client import LLMError

    def _complete(*, purpose, **kwargs):
        if fail:
            raise LLMError('down', retryable=(fail == 'retryable'))
        if purpose == 'consultation.draft_statements':
            return {'statements': drafted if drafted is not None else DRAFTED}
        if purpose == 'consultation.report_narrative':
            if narrative is None:
                raise LLMError('no narrative', retryable=False)
            return narrative(kwargs['prompt']) if callable(narrative) else narrative
        if purpose == 'consultation.screen_statement':
            return screening or {'result': 'ok', 'concern': 'none'}
        raise AssertionError(purpose)

    for target in (
        'app.consultations.drafting.complete_json',
        'app.consultations.narrative.complete_json',
        'app.consultations.screening.complete_json',
    ):
        monkeypatch.setattr(target, _complete)


def _draft_consultation(host, monkeypatch, **overrides):
    _mock_llm(monkeypatch)
    consultation = service.create_consultation(
        host,
        question=overrides.get('question', 'How should we use next year’s surplus?'),
        organisation_name='Riverside Members Club',
        audience_label='Our members',
        audience_size=overrides.get('audience_size', 200),
    )
    jobs.enqueue_drafting(consultation)
    drain_jobs()
    return consultation


def _live_consultation(host, monkeypatch, **overrides):
    consultation = _draft_consultation(host, monkeypatch, **overrides)
    service.publish(consultation, covered_by=Consultation.COVERED_BY_COMPLIMENTARY)
    return consultation


def _participant(app, client_id=None):
    """A browser that has opened the page: it holds the voter cookie. (The real
    cookie is Secure, which the test client would not send back over http.)"""
    client = app.test_client()
    client.set_cookie('ss_voter_client_id', client_id or secrets.token_hex(32))
    g.pop('_login_user', None)
    return client


def _vote_all(client, consultation, vote_for):
    for statement in service.published_statements(consultation):
        response = client.post(
            f'/c/{consultation.access_token}/vote',
            json={'statement_id': statement.id, 'vote': vote_for(statement)},
        )
        assert response.status_code == 200, response.get_data(as_text=True)


# ── Feature flag ────────────────────────────────────────────────────────────

def test_everything_is_404_while_the_feature_is_off(app, db, host, client, monkeypatch):
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = True
    consultation = _live_consultation(host, monkeypatch)
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = False
    _login(client, host)

    for path in (
        '/consultations/start', '/consultations/new', '/consultations/mine', '/consultations/account',
        f'/consultations/{consultation.id}', f'/c/{consultation.access_token}', '/help/consultations',
    ):
        assert client.get(path).status_code == 404, path
    assert client.get('/consultations').status_code == 200, 'the marketing page stays up'


# ── Host journey ────────────────────────────────────────────────────────────

def test_host_goes_from_question_to_shared_report(app, enabled, host, client, monkeypatch):
    _mock_llm(monkeypatch)
    _login(client, host)

    created = client.post('/consultations/new', data={
        'question': 'How should we use next year’s surplus?',
        'organisation_name': 'Riverside Members Club',
        'audience_label': 'Our members',
        'audience_size': '40',
        'context': 'We have a surplus of about twelve thousand pounds.',
    })
    assert created.status_code == 302
    consultation = Consultation.query.one()
    assert created.headers['Location'].endswith(f'/consultations/{consultation.id}/statements')

    # Drafting runs in the background; the page says so, then shows the result.
    working = client.get(f'/consultations/{consultation.id}/statements').get_data(as_text=True)
    assert 'Drafting your statements' in working
    assert client.get(f'/consultations/{consultation.id}/statements/status.json').get_json()['status'] == 'working'
    drain_jobs()
    drafted = client.get(f'/consultations/{consultation.id}/statements').get_data(as_text=True)
    assert 'We should spend the surplus on lower fees for members.' in drafted
    assert 'Drafted by AI' in drafted

    assert client.post(f'/consultations/{consultation.id}/statements/add', data={
        'content': 'The committee should publish a spending plan first.',
    }).status_code == 302

    assert client.post(f'/consultations/{consultation.id}/settings', data={
        'open_days': '5', 'allow_audience_statements': 'y',
    }).status_code == 302

    # Not entitled yet: the page offers both ways to pay and does not go live.
    pay = client.get(f'/consultations/{consultation.id}/go-live').get_data(as_text=True)
    assert '£249' in pay and '£950' in pay
    client.post(f'/consultations/{consultation.id}/go-live', data={})
    assert Consultation.query.one().is_draft

    db_purchase = ConsultationPurchase(
        user_id=host.id, stripe_checkout_session_id='cs_test_1', stripe_payment_intent_id='pi_1',
        amount_pence=24900,
    )
    from app import db
    db.session.add(db_purchase)
    db.session.commit()

    live = client.post(f'/consultations/{consultation.id}/go-live', data={})
    assert live.headers['Location'].endswith(f'/consultations/{consultation.id}/share')
    consultation = Consultation.query.one()
    assert consultation.is_live and consultation.covered_by == 'purchase'
    assert db_purchase.consumed_at is not None and not db_purchase.is_unused
    assert 'Your consultation is live' in enabled

    share = client.get(f'/consultations/{consultation.id}/share').get_data(as_text=True)
    assert f'/c/{consultation.access_token}' in share
    svg = client.get(f'/consultations/{consultation.id}/qr.svg')
    assert svg.status_code == 200 and svg.mimetype == 'image/svg+xml'
    png = client.get(f'/consultations/{consultation.id}/qr.png')
    assert png.data[:8] == b'\x89PNG\r\n\x1a\n'
    assert client.get(f'/consultations/{consultation.id}/present').status_code == 200

    # Thirty people take part: most agree with the first statement.
    statements = service.published_statements(consultation)
    for number in range(30):
        participant = _participant(app)
        _vote_all(participant, consultation, lambda s: 1 if s.id == statements[0].id and number < 26 else (-1 if number % 2 else 1))

    _login(client, host)
    dashboard = client.get(f'/consultations/{consultation.id}').get_data(as_text=True)
    assert 'They agree' in dashboard
    status = client.get(f'/consultations/{consultation.id}/status.json').get_json()
    assert status['participants'] == 30 and status['votes'] == 30 * len(statements)

    closed = client.post(f'/consultations/{consultation.id}/close', data={})
    assert closed.headers['Location'].endswith('/report')
    assert 'being built' in client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    drain_jobs()
    assert 'Your consultation report is ready' in enabled

    report_page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'Where participants agree' in report_page
    assert 'These results describe the 30 people who took part' in report_page
    assert '75%' in report_page, 'response rate: 30 of 40 invited'

    csv_file = client.get(f'/consultations/{consultation.id}/results.csv').get_data(as_text=True)
    assert 'We should spend the surplus on lower fees for members.' in csv_file

    # Private until shared; the share link stops working when unshared.
    report = ConsultationReport.query.one()
    assert report.share_token is None
    client.post(f'/consultations/{consultation.id}/report/share', data={})
    token = ConsultationReport.query.one().share_token
    outsider = _participant(app)
    shared = outsider.get(f'/r/{token}')
    assert shared.status_code == 200 and 'Where participants agree' in shared.get_data(as_text=True)
    _login(client, host)
    client.post(f'/consultations/{consultation.id}/report/unshare', data={})
    assert _participant(app).get(f'/r/{token}').status_code == 404


def test_another_account_cannot_reach_a_consultation(app, enabled, host, client, monkeypatch):
    from app import db
    consultation = _live_consultation(host, monkeypatch)
    other = User(username='other', email='other@example.org', password='x', email_verified=True)
    admin = User(username='admin', email='admin@example.org', password='x', email_verified=True, is_admin=True)
    db.session.add_all([other, admin])
    db.session.commit()

    for user in (other, admin):
        _login(client, user)
        for path in ('', '/share', '/report', '/moderation', '/status.json', '/results.csv', '/qr.svg'):
            assert client.get(f'/consultations/{consultation.id}{path}').status_code == 404, (user.username, path)
        assert client.post(f'/consultations/{consultation.id}/close', data={}).status_code == 404
    assert Consultation.query.one().is_live


def test_statements_cannot_be_reworded_once_live(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    original = statement.content
    _login(client, host)

    client.post(
        f'/consultations/{consultation.id}/statements/{statement.id}/edit',
        data={'content': 'A completely different claim that nobody voted on.'},
    )
    assert Statement.query.get(statement.id).content == original

    client.post(f'/consultations/{consultation.id}/statements/{statement.id}/remove', data={})
    assert statement.id not in [s.id for s in service.published_statements(consultation)]


def test_going_live_needs_enough_statements(app, enabled, host, monkeypatch):
    _mock_llm(monkeypatch, drafted=DRAFTED[:2])
    consultation = service.create_consultation(host, question='What should we change first?', organisation_name='Org')
    jobs.enqueue_drafting(consultation)
    drain_jobs()

    with pytest.raises(service.ConsultationError):
        service.publish(consultation, covered_by='complimentary')
    assert consultation.is_draft and consultation.discussion.is_closed


# ── Participant page ────────────────────────────────────────────────────────

def test_participant_page_needs_no_session_and_loads_no_trackers(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    client = _participant(app)

    response = client.get(f'/c/{consultation.access_token}')

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert consultation.question in body
    for tracker in ('posthog', 'googletagmanager', 'GTM-', 'cookieyes'):
        assert tracker not in body, tracker
    cookies = {cookie.split('=')[0] for cookie in response.headers.getlist('Set-Cookie')}
    assert 'session' not in cookies, 'the page must not open a server session'
    assert cookies == {'ss_voter_client_id'}, 'the page promises exactly one cookie'
    assert 'no-store' in response.headers['Cache-Control']
    assert 'noindex' in response.headers['X-Robots-Tag']


def test_a_live_consultation_with_nothing_left_to_vote_on_says_so(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    _login(client, host)
    for statement in list(service.published_statements(consultation)):
        response = client.post(
            f'/consultations/{consultation.id}/statements/{statement.id}/remove',
            data={},
            follow_redirects=True,
        )

    assert 'nothing to answer' in response.get_data(as_text=True)
    page = _participant(app).get(f'/c/{consultation.access_token}')
    body = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'Nothing to answer yet' in body
    assert 'Your answers are in' not in body
    assert 'no-referrer' in page.headers['Referrer-Policy']


def test_votes_are_anonymous_even_for_a_signed_in_participant(app, enabled, host, client, monkeypatch):
    captured = []
    monkeypatch.setattr('app.discussions.statements.capture_statement_voted', lambda *a, **k: captured.append(a))
    consultation = _live_consultation(host, monkeypatch)
    _login(client, host)
    client.get(f'/c/{consultation.access_token}')

    _vote_all(client, consultation, lambda s: 1)

    votes = StatementVote.query.filter_by(discussion_id=consultation.discussion_id).all()
    assert votes and all(v.user_id is None for v in votes)
    assert all(v.posthog_distinct_id is None for v in votes)
    client_id = client.get_cookie('ss_voter_client_id').value
    site_fingerprint = hashlib.sha256(client_id.encode()).hexdigest()
    assert {v.session_fingerprint for v in votes} != {site_fingerprint}, (
        'a consultation vote must not carry the visitor\'s site-wide fingerprint'
    )
    assert captured == [], 'consultation votes must not be sent to analytics'

    # Signing in later must not attach those votes to the account.
    from app.auth.routes import merge_anonymous_statement_votes_into_user
    with app.test_request_context('/', headers={'Cookie': f'ss_voter_client_id={client_id}'}):
        merge_anonymous_statement_votes_into_user(host)
    assert all(v.user_id is None for v in StatementVote.query.filter_by(discussion_id=consultation.discussion_id))


def test_one_device_is_one_participant_and_can_change_its_answer(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    client = _participant(app)

    for value in (1, -1):
        assert client.post(
            f'/c/{consultation.access_token}/vote', json={'statement_id': statement.id, 'vote': value},
        ).status_code == 200

    votes = StatementVote.query.filter_by(statement_id=statement.id).all()
    assert [v.vote for v in votes] == [-1]
    assert service.participation(consultation)['participants'] == 1
    # Coming back resumes: the page knows what this device already answered.
    page = client.get(f'/c/{consultation.access_token}').get_data(as_text=True)
    assert f'"{statement.id}": -1' in page


def test_vote_is_refused_for_bad_input_closed_or_foreign_statements(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    other = _live_consultation(host, monkeypatch, question='A second consultation entirely?')
    foreign = service.published_statements(other)[0]
    statement = service.published_statements(consultation)[0]
    client = _participant(app)
    url = f'/c/{consultation.access_token}/vote'

    assert client.post(url, json={'statement_id': statement.id, 'vote': 5}).status_code == 400
    assert client.post(url, json={'statement_id': 'x', 'vote': 1}).status_code == 400
    assert client.post(url, json={'statement_id': foreign.id, 'vote': 1}).status_code == 404
    assert client.post('/c/not-a-real-token/vote', json={'statement_id': statement.id, 'vote': 1}).status_code == 404

    service.close(consultation)
    assert client.post(url, json={'statement_id': statement.id, 'vote': 1}).status_code == 409
    closed_page = client.get(f'/c/{consultation.access_token}').get_data(as_text=True)
    assert 'Voting has closed' in closed_page


def test_a_vote_clash_asks_the_page_to_retry(app, enabled, host, monkeypatch):
    """409 means voting has closed. A database clash must not use that code."""
    from sqlalchemy.exc import IntegrityError

    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]

    def clash(*_args, **_kwargs):
        raise IntegrityError('INSERT', {}, Exception('clash'))

    monkeypatch.setattr('app.discussions.statements._persist_vote_with_upsert', clash)
    response = _participant(app).post(
        f'/c/{consultation.access_token}/vote',
        json={'statement_id': statement.id, 'vote': 1},
    )
    assert response.status_code == 503
    assert response.get_json()['error'] == 'busy'


def test_rotating_the_link_cuts_off_the_old_one(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    old_token = consultation.access_token
    statement = service.published_statements(consultation)[0]
    _login(client, host)

    client.post(f'/consultations/{consultation.id}/rotate-link', data={})

    new_token = Consultation.query.one().access_token
    participant = _participant(app)
    assert new_token != old_token
    assert participant.get(f'/c/{old_token}').status_code == 404
    assert participant.post(f'/c/{old_token}/vote', json={'statement_id': statement.id, 'vote': 1}).status_code == 404
    assert participant.get(f'/c/{new_token}').status_code == 200


def test_a_draft_is_not_open_but_its_owner_can_preview_it(app, enabled, host, client, monkeypatch):
    consultation = _draft_consultation(host, monkeypatch)

    assert 'Not open yet' in _participant(app).get(f'/c/{consultation.access_token}').get_data(as_text=True)
    _login(client, host)
    preview = client.get(f'/c/{consultation.access_token}').get_data(as_text=True)
    assert 'Your answers here are not recorded' in preview


# ── Link-only: nothing leaks onto the public site ───────────────────────────

def test_a_consultation_has_no_public_discussion_pages(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    discussion = consultation.discussion
    statement = service.published_statements(consultation)[0]
    assert discussion.link_only and discussion.creator_id is None

    for user in (None, host):
        if user:
            _login(client, user)
        for path in (
            f'/discussions/{discussion.id}',
            f'/discussions/{discussion.id}/{discussion.slug}',
            f'/discussions/{discussion.id}/embed',
            f'/discussions/{discussion.id}/consensus',
            f'/discussions/{discussion.id}/consensus/report',
            f'/api/discussions/{discussion.id}/consensus/export',
            f'/api/discussions/{discussion.id}/snapshot',
            f'/discussions/api/discussions/{discussion.id}/statements',
            f'/statements/{statement.id}',
            f'/api/statements/{statement.id}/votes',
            f'/discussions/{discussion.id}/statements/create',
        ):
            status = client.get(path).status_code
            assert status in (403, 404, 410), (path, status)
    assert client.post(
        f'/statements/{statement.id}/vote', json={'vote': 1}, headers={'X-Embed-Request': 'true'},
    ).status_code == 404


def test_a_consultation_never_appears_in_public_listings(app, enabled, host, client, monkeypatch):
    marker = 'Zzyzx surplus question that must stay private'
    consultation = _live_consultation(host, monkeypatch, question=f'{marker}?')

    assert Discussion.query.filter(Discussion.publicly_listable()).count() == 0
    for path in ('/', '/discussions/search', f'/discussions/search?q=Zzyzx', '/sitemap.xml', '/news'):
        response = client.get(path)
        assert marker not in response.get_data(as_text=True), path
    from app.lib.translation_worker import _untranslated_discussions, _untranslated_statements
    assert _untranslated_discussions('fr', 50) == []
    assert _untranslated_statements('fr', 50) == []
    assert consultation.discussion.is_publicly_listable is False


# ── Audience suggestions ────────────────────────────────────────────────────

def _suggest(client, consultation, content):
    return client.post(f'/c/{consultation.access_token}/statements', json={'content': content})


def test_a_suggestion_is_hidden_until_the_host_approves_it(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    consultation.allow_audience_statements = True
    from app import db
    db.session.commit()
    participant = _participant(app)

    assert _suggest(participant, consultation, 'We should refund every member ten pounds.').status_code == 200
    suggestion = Statement.query.filter_by(source='user_submitted').one()
    assert suggestion.mod_status == ModStatus.PENDING
    assert suggestion.id not in [s.id for s in service.published_statements(consultation)]
    assert participant.post(
        f'/c/{consultation.access_token}/vote', json={'statement_id': suggestion.id, 'vote': 1},
    ).status_code == 404, 'a held statement cannot be voted on'

    drain_jobs()  # screening
    assert 'Suggested statements are waiting for you' in enabled
    _login(client, host)
    queue = client.get(f'/consultations/{consultation.id}/moderation').get_data(as_text=True)
    assert 'We should refund every member ten pounds.' in queue
    assert 'Screening found no problems.' in queue

    client.post(f'/consultations/{consultation.id}/moderation/{suggestion.id}/approve', data={})
    assert suggestion.id in [s.id for s in service.published_statements(consultation)]


def test_screening_rejects_abuse_before_it_reaches_the_host(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    consultation.allow_audience_statements = True
    from app import db
    db.session.commit()
    _mock_llm(monkeypatch, screening={'result': 'reject', 'concern': 'names_a_person'})

    _suggest(_participant(app), consultation, 'Our treasurer John Smith is stealing from us.')
    drain_jobs()

    suggestion = Statement.query.filter_by(source='user_submitted').one()
    assert suggestion.mod_status == ModStatus.REJECTED
    assert service.pending_statements(consultation) == []
    assert 'Suggested statements are waiting for you' not in enabled


def test_suggestions_wait_for_the_host_when_screening_is_down(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    consultation.allow_audience_statements = True
    from app import db
    db.session.commit()
    _mock_llm(monkeypatch, fail='permanent')

    _suggest(_participant(app), consultation, 'We should refund every member ten pounds.')
    drain_jobs()

    assert len(service.pending_statements(consultation)) == 1
    assert jobs.screening_notes(consultation)[service.pending_statements(consultation)[0].id]['result'] == 'unscreened'


def test_suggestions_are_refused_when_switched_off_or_spam(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    participant = _participant(app)
    assert _suggest(participant, consultation, 'We should refund every member ten pounds.').status_code == 409

    consultation.allow_audience_statements = True
    from app import db
    db.session.commit()
    assert _suggest(participant, consultation, 'short').status_code == 400
    spam = 'Buy pills now, contact me on telegram @dealer or whatsapp +44 7700 900123 for crypto payment'
    assert _suggest(participant, consultation, spam).status_code == 400
    assert Statement.query.filter_by(source='user_submitted').count() == 0


# ── When things go wrong ────────────────────────────────────────────────────

def test_drafting_failure_leaves_the_host_able_to_write_by_hand(app, enabled, host, client, monkeypatch):
    _mock_llm(monkeypatch, fail='permanent')
    consultation = service.create_consultation(host, question='What should we change first?', organisation_name='Org')
    jobs.enqueue_drafting(consultation)
    drain_jobs()

    assert jobs.drafting_state(consultation)['status'] == 'failed'
    assert 'We could not draft your statements' in enabled
    _login(client, host)
    page = client.get(f'/consultations/{consultation.id}/statements').get_data(as_text=True)
    assert 'We could not draft statements this time' in page
    assert 'Add a statement of your own' in page


def test_drafting_retries_a_provider_outage_then_gives_up_cleanly(app, enabled, host, monkeypatch):
    from app import db
    _mock_llm(monkeypatch, fail='retryable')
    consultation = service.create_consultation(host, question='What should we change first?', organisation_name='Org')
    job, _created = jobs.enqueue_drafting(consultation)

    for _attempt in range(3):
        job.run_after = utcnow_naive()
        db.session.commit()
        drain_jobs()

    assert job.status == BackgroundJob.STATUS_DEAD_LETTER and job.attempts == 3
    assert enabled.count('We could not draft your statements') == 1


def test_drafting_is_capped_per_account_per_day(app, enabled, host, monkeypatch):
    app.config['CONSULTATION_DRAFTS_PER_DAY'] = 2
    consultation = _draft_consultation(host, monkeypatch)
    jobs.enqueue_drafting(consultation)
    drain_jobs()

    job, created = jobs.enqueue_drafting(consultation)
    assert job is None and created is False


def test_the_report_is_built_even_when_the_narrative_model_is_down(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    for _number in range(12):
        _vote_all(_participant(app), consultation, lambda s: 1)
    _mock_llm(monkeypatch, fail='retryable')

    jobs.close_and_report(consultation)
    drain_jobs()

    report = ConsultationReport.query.one()
    assert report.narrative_source == 'template'
    assert 'participants' in report.narrative['headline']
    assert 'Your consultation report is ready' in enabled


def test_low_turnout_still_gets_a_report_that_says_so(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    for _number in range(4):
        _vote_all(_participant(app), consultation, lambda s: 1)

    jobs.close_and_report(consultation)
    drain_jobs()

    report = ConsultationReport.query.one()
    assert report.data['is_low_turnout'] is True
    assert report.data['counts']['too_few_votes'] == report.data['statement_count']
    _login(client, host)
    page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'Too few people have taken part' in page
    assert '4 of 4 agreed' in page
    assert 'Turnout was low' in page


def test_the_sweep_closes_due_consultations_and_sends_each_notice_once(app, enabled, host, monkeypatch):
    from datetime import timedelta
    from app import db
    consultation = _live_consultation(host, monkeypatch)
    _vote_all(_participant(app), consultation, lambda s: 1)
    consultation.published_at = utcnow_naive() - timedelta(days=6)
    consultation.closes_at = utcnow_naive() + timedelta(hours=6)
    db.session.commit()

    jobs.run_sweep()
    jobs.run_sweep()
    assert enabled.count('The first responses are in') == 1
    assert enabled.count('Your consultation closes tomorrow') == 1

    consultation.closes_at = utcnow_naive() - timedelta(minutes=1)
    db.session.commit()
    assert jobs.run_sweep()['closed'] == 1
    assert Consultation.query.one().is_closed
    drain_jobs()
    assert ConsultationReport.query.one().kind == 'final'
    assert jobs.run_sweep()['closed'] == 0

    # Reopening lets people vote again on the same link.
    service.set_closing_time(consultation, utcnow_naive() + timedelta(days=7))
    assert consultation.is_live and not consultation.discussion.is_closed


def test_deleting_a_consultation_removes_its_votes_and_keeps_the_purchase_spent(app, enabled, host, monkeypatch):
    from app import db
    consultation = _draft_consultation(host, monkeypatch)
    purchase = ConsultationPurchase(user_id=host.id, stripe_checkout_session_id='cs_del', amount_pence=24900)
    db.session.add(purchase)
    db.session.commit()
    billing.go_live(consultation, host)
    _vote_all(_participant(app), consultation, lambda s: 1)
    discussion_id = consultation.discussion_id

    service.delete_consultation(consultation)

    assert Consultation.query.count() == 0
    assert db.session.get(Discussion, discussion_id) is None
    assert StatementVote.query.filter_by(discussion_id=discussion_id).count() == 0
    assert Statement.query.filter_by(discussion_id=discussion_id).count() == 0
    assert billing.unused_purchases(host) == [], 'a spent purchase must not come back'


# ── Product page, sign-up and help ──────────────────────────────────────────

def test_product_page_states_prices_and_meets_seo_rules(app, enabled, client):
    html = client.get('/consultations/self-serve').get_data(as_text=True)

    assert 'See where your audience agrees, disagrees or is unsure.' in html
    assert '£249' in html and '£950' in html and '£2,500' in html
    assert html.count('rel="canonical"') == 1
    assert 'href="http://localhost/consultations/self-serve"' in html
    for block in ('og:title', 'og:description', 'twitter:title', 'twitter:description'):
        assert block in html
    assert '"@type": "FAQPage"' in html
    assert '/consultations/self-serve' in client.get('/sitemap.xml').get_data(as_text=True)
    assert 'Run a consultation' in html
    home = client.get('/').get_data(as_text=True)
    assert 'Run a consultation' in home
    assert '/consultations/self-serve' in home
    platform = client.get('/platform').get_data(as_text=True)
    assert 'Run a consultation with your own audience from £249' in platform
    # The facilitated page points across, and only while the product is on.
    facilitated = client.get('/consultations').get_data(as_text=True)
    assert 'Would you rather run one yourself?' in facilitated
    assert 'See how to run one yourself' in facilitated


def test_product_page_is_not_advertised_while_the_feature_is_off(app, db, client):
    assert 'self-serve' not in client.get('/sitemap.xml').get_data(as_text=True)
    assert 'Would you rather run one yourself?' not in client.get('/consultations').get_data(as_text=True)
    assert 'Run a consultation' not in client.get('/').get_data(as_text=True)
    assert 'from £249' not in client.get('/platform').get_data(as_text=True)


def test_a_new_host_signs_in_with_an_emailed_link(app, enabled, client, monkeypatch):
    links = []
    monkeypatch.setattr(
        'app.lib.magic_login_dispatch.send_magic_login_email',
        lambda user, url, submitted_email=None: links.append((user.email, url)) or True,
    )

    page = client.get('/consultations/start').get_data(as_text=True)
    assert 'Email me a sign-in link' in page

    sent = client.post('/consultations/start', data={'email': 'new.host@example.org'})

    assert 'Check your inbox' in sent.get_data(as_text=True)
    email, url = links[0]
    assert email == 'new.host@example.org'
    assert '/auth/login/magic-link/' in url and url.endswith('next=/consultations/new')
    user = User.query.filter_by(email='new.host@example.org').one()
    assert user.email_verified is False

    # The same address again reuses the account rather than creating a second.
    client.post('/consultations/start', data={'email': 'new.host@example.org'})
    assert User.query.filter_by(email='new.host@example.org').count() == 1


def test_sign_up_refuses_disposable_addresses_and_bots(app, enabled, client, monkeypatch):
    monkeypatch.setattr(
        'app.lib.magic_login_dispatch.send_magic_login_email',
        lambda *args, **kwargs: pytest.fail('no email should be sent'),
    )

    client.post('/consultations/start', data={'email': 'someone@mailinator.com'})
    client.post('/consultations/start', data={'email': 'bot@example.org', 'website_url': 'http://spam.example'})

    assert User.query.count() == 0


def test_a_signed_in_visitor_goes_straight_to_the_first_step(app, enabled, host, client):
    _login(client, host)
    assert client.get('/consultations/start').headers['Location'].endswith('/consultations/new')
    assert 'What do you want to know?' in client.get('/consultations/new').get_data(as_text=True)
    # With no consultations yet, "Your consultations" starts one.
    assert client.get('/consultations/mine').headers['Location'].endswith('/consultations/new')


def test_help_guide_explains_the_result_rules(app, enabled, client):
    html = client.get('/help/consultations').get_data(as_text=True)

    assert 'How results are called' in html
    assert 'Fewer than 10 people voted on the statement' in html
    assert 'at least 35%' in html


def test_every_host_screen_renders(app, enabled, host, client, monkeypatch):
    draft = _draft_consultation(host, monkeypatch)
    live = _live_consultation(host, monkeypatch, question='A second live consultation to render?')
    _login(client, host)

    pages = {
        '/consultations/mine': 'Your consultations',
        '/consultations/account': 'Plan and billing',
        f'/consultations/{draft.id}/question': 'What do you want to know?',
        f'/consultations/{draft.id}/statements': 'A good statement',
        f'/consultations/{draft.id}/settings': 'How should it run?',
        f'/consultations/{draft.id}/go-live': 'Ready to go live?',
        f'/consultations/{live.id}': 'Results so far',
        f'/consultations/{live.id}/share': 'An invitation you can paste',
        f'/consultations/{live.id}/moderation': 'Suggested statements',
        f'/consultations/{live.id}/report': 'No report yet',
    }
    for path, expected in pages.items():
        response = client.get(path)
        assert response.status_code == 200, path
        body = response.get_data(as_text=True)
        assert expected in body, path
        assert 'noindex' in body, f'{path} must not be indexed'
    # A draft has no dashboard, share page or report yet.
    assert client.get(f'/consultations/{draft.id}').status_code == 302
    assert client.get(f'/consultations/{draft.id}/share').status_code == 302


def test_interim_report_is_marked_as_interim(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    for _number in range(12):
        _vote_all(_participant(app), consultation, lambda s: 1)
    _login(client, host)

    client.post(f'/consultations/{consultation.id}/report/build', data={})
    drain_jobs()

    page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'Interim report. Voting was still open' in page
    assert 'Your consultation report is ready' not in enabled, 'no "report ready" email for an interim report'


def test_participants_see_others_results_only_when_allowed_and_after_voting(app, enabled, host, monkeypatch):
    from app import db
    consultation = _live_consultation(host, monkeypatch)
    participant = _participant(app)
    url = f'/c/{consultation.access_token}/results.json'
    assert participant.get(url).status_code == 404

    consultation.show_results_to_participants = True
    db.session.commit()
    assert participant.get(url).status_code == 403, 'vote first'

    _vote_all(participant, consultation, lambda s: 1)
    rows = participant.get(url).get_json()['results']
    assert len(rows) == len(service.published_statements(consultation))
    assert all(row['enough_votes'] is False for row in rows), 'one voter is too few to show shares'


# ── Guards ──────────────────────────────────────────────────────────────────

def test_listing_queries_use_the_one_public_listing_rule():
    """A raw ``partner_env != 'test'`` filter would list link-only consultations.

    Every listing, feed, email and sweep over discussions must use
    ``Discussion.publicly_listable()`` so that one definition covers both
    partner sandboxes and consultations.
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parents[1] / 'app'
    # Partner-scoped code filters by its own partner and environment on purpose.
    allowed = {'app/models/discussions.py', 'app/api/partner.py', 'app/partner/routes.py', 'app/commands.py'}
    pattern = re.compile(r"""partner_env\s*!=\s*['"]test['"]""")
    offenders = [
        str(path.relative_to(app_dir.parent))
        for path in sorted(app_dir.rglob('*.py'))
        if str(path.relative_to(app_dir.parent)) not in allowed and pattern.search(path.read_text())
    ]
    assert offenders == []


def test_the_clustering_engine_never_runs_on_a_consultation(app, enabled, host, monkeypatch):
    from app.discussions.jobs import enqueue_consensus_job
    from app.models import ConsensusJob

    consultation = _live_consultation(host, monkeypatch)
    _vote_all(_participant(app), consultation, lambda s: 1)

    job, created, _message = enqueue_consensus_job(consultation.discussion_id)

    assert job is None and created is False
    assert ConsensusJob.query.count() == 0


def test_pdf_download_falls_back_to_print_where_the_renderer_is_missing(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    jobs.close_and_report(consultation)
    drain_jobs()
    monkeypatch.setattr('app.consultations.pdf._weasyprint', lambda: None)
    monkeypatch.setattr('app.consultations.host.pdf_rendering_available', lambda: False)
    _login(client, host)

    page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)

    assert 'Print or save as PDF' in page and 'Download PDF' not in page
    assert client.get(f'/consultations/{consultation.id}/report.pdf').status_code == 404


def test_pdf_is_rendered_once_then_served_from_storage(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    renders, stored = [], {}

    class _FakeWeasyPrint:
        class urls:
            class URLFetcher:
                def __init__(self, **options):
                    self.options = options

        class HTML:
            def __init__(self, string, base_url, url_fetcher):
                assert 'Consultation report' in string
                assert url_fetcher.options == {'allowed_protocols': ('file', 'data'), 'allow_redirects': False}
                renders.append(base_url)

            def write_pdf(self):
                return b'%PDF-fake'

    monkeypatch.setattr('app.consultations.pdf._weasyprint', lambda: _FakeWeasyPrint)
    monkeypatch.setattr('app.consultations.host.pdf_rendering_available', lambda: True)
    monkeypatch.setattr('app.consultations.pdf.upload_bytes_to_object_storage', lambda key, data: stored.update({key: data}) or True)
    monkeypatch.setattr('app.consultations.pdf.download_bytes_from_object_storage', lambda key: stored.get(key))
    jobs.close_and_report(consultation)
    drain_jobs()
    _login(client, host)

    first = client.get(f'/consultations/{consultation.id}/report.pdf')
    second = client.get(f'/consultations/{consultation.id}/report.pdf')

    assert first.data == second.data == b'%PDF-fake'
    assert first.mimetype == 'application/pdf'
    assert len(renders) == 1, 'rendered in the report job, then served from storage'
    key = ConsultationReport.query.one().pdf_storage_key
    assert key in stored and len(key.split('-')[-1]) >= 32, 'the storage key must be unguessable'


def test_example_report_is_built_from_a_public_discussion_only(app, enabled, host, client, monkeypatch):
    from app import db
    public = Discussion(title='Should cities charge for parking?', slug='parking', has_native_statements=True, geographic_scope='global')
    db.session.add(public)
    db.session.flush()
    statement = Statement(discussion_id=public.id, content='Parking charges should fund public transport.')
    db.session.add(statement)
    db.session.flush()
    for number in range(20):
        db.session.add(StatementVote(
            statement_id=statement.id, discussion_id=public.id, session_fingerprint=f'fp-{number}', vote=1,
        ))
    db.session.commit()

    app.config['CONSULTATION_EXAMPLE_DISCUSSION_ID'] = public.id
    page = client.get('/consultations/example-report').get_data(as_text=True)
    assert 'This is an example' in page and 'Parking charges should fund public transport.' in page
    assert 'Where participants agree' in page and 'real votes on a public' in page

    # A consultation can never be used as the public example: the made-up one is shown instead.
    private = _live_consultation(host, monkeypatch)
    app.config['CONSULTATION_EXAMPLE_DISCUSSION_ID'] = private.discussion_id
    page = client.get('/consultations/example-report').get_data(as_text=True)
    assert 'How should we use next year' not in page.split('Riverside Members Club')[0] or 'made-up votes' in page
    assert 'made-up votes' in page and DRAFTED[0]['content'] not in page


def test_the_worked_example_obeys_the_same_rules_as_a_real_report(app, enabled, client):
    from app.consultations import example
    from app.consultations.narrative import validate_narrative

    with app.test_request_context():
        data = example.example_report_data()
        narrative = example.example_narrative()

    assert validate_narrative(narrative, data) is None
    # Every kind of finding appears, so the example shows the whole report.
    assert all(data['counts'][verdict] >= 1 for verdict in ('agrees', 'disagrees', 'unsure', 'split', 'no_clear_result'))
    assert data['vote_count'] == sum(row['total'] for row in data['statements'])
    assert all(row['total'] <= data['participant_count'] for row in data['statements'])

    page = client.get('/consultations/example-report')
    text = page.get_data(as_text=True)
    assert page.status_code == 200
    assert 'made-up organisation and made-up votes' in text and 'This example uses made-up votes' in text
    assert 'Control and openness' in text and 'Where participants are split' in text


def test_anyone_can_try_the_participant_page_and_nothing_is_recorded(app, enabled):
    visitor = app.test_client()

    response = visitor.get('/consultations/demo')
    page = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Nothing you answer is recorded' in page and 'See the report this produces' in page
    assert 'Members should vote on any spending above £10,000.' in page
    assert json.loads(page.split('id="consultation-data" type="application/json">')[1].split('</script>')[0])['preview'] is True
    assert 'Set-Cookie' not in response.headers, 'the demonstration sets no cookie'
    for tracker in ('posthog', 'googletagmanager', 'gtag('):
        assert tracker not in page.lower()
    assert StatementVote.query.count() == 0 and Consultation.query.count() == 0


def test_the_product_page_leads_to_the_example_the_demo_and_sign_up(app, enabled, client):
    page = client.get('/consultations/self-serve').get_data(as_text=True)

    for href in ('/consultations/start', '/consultations/example-report', '/consultations/demo'):
        assert f'href="{href}"' in page
    assert 'no card needed' in page
    assert 'Why not a survey or a live poll?' in page


def test_host_screens_do_not_send_their_content_to_analytics(app, enabled, host, client, monkeypatch):
    app.config['POSTHOG_API_KEY'] = 'phc_test'
    consultation = _live_consultation(host, monkeypatch)
    _login(client, host)

    page = client.get(f'/consultations/{consultation.id}').get_data(as_text=True)

    if 'posthog.init' in page:
        assert 'autocapture: false' in page and 'disable_session_recording: true' in page


def test_link_tokens_are_removed_from_error_reports():
    from app.lib.sentry_config import scrub_capability_urls

    event = scrub_capability_urls({
        'transaction': '/c/k-sTMjOnk-kPXmkTwH5_Wg/vote',
        'request': {
            'url': 'https://societyspeaks.io/c/k-sTMjOnk-kPXmkTwH5_Wg/vote',
            'headers': {'Referer': 'https://societyspeaks.io/r/Zb3xQ0vVx1lB9d2mE4nT7A'},
        },
        'breadcrumbs': {'values': [{'data': {'url': 'https://societyspeaks.io/c/k-sTMjOnk-kPXmkTwH5_Wg'}}]},
    })

    assert 'k-sTMjOnk' not in json.dumps(event) and 'Zb3xQ0vVx' not in json.dumps(event)
    assert event['request']['url'] == 'https://societyspeaks.io/c/[token]/vote'
    # Ordinary addresses are left alone.
    assert scrub_capability_urls({'request': {'url': 'https://societyspeaks.io/consultations/12'}})['request']['url'].endswith('/consultations/12')


# ── Nothing outside the consultation routes can reach a consultation ────────

def _admin(db):
    admin = User(username='site-admin', email='admin@example.org', password='x', email_verified=True, is_admin=True)
    db.session.add(admin)
    db.session.commit()
    return admin


def test_site_admins_cannot_see_or_change_a_customers_consultation(app, db, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    discussion_id = consultation.discussion_id
    _login(client, _admin(db))

    listing = client.get('/admin/discussions?q=surplus').get_data(as_text=True)
    assert 'How should we use next year' not in listing
    assert client.get(f'/admin/discussions/{discussion_id}/statements').status_code == 404
    assert client.post(f'/admin/discussions/{discussion_id}/toggle-closed').status_code == 404
    assert client.post(f'/admin/discussions/{discussion_id}/delete').status_code == 404
    assert client.post(f'/admin/statements/{statement.id}/delete').status_code == 404
    assert client.post(f'/admin/statements/{statement.id}/restore').status_code == 404

    db.session.expire_all()
    assert Consultation.query.one().is_live and not db.session.get(Discussion, discussion_id).is_closed
    assert db.session.get(Statement, statement.id).is_deleted is False


def test_the_site_wide_spam_sweep_leaves_consultations_alone(app, db, enabled, host, monkeypatch):
    from app.lib import content_spam

    consultation = _live_consultation(host, monkeypatch)
    monkeypatch.setattr(
        content_spam, 'assess_user_content_spam',
        lambda text: content_spam.ContentSpamVerdict(blocked=True, score=9, reasons=('test',), threshold=1),
    )

    result = content_spam.hide_matching_unsolicited_content(apply=True)

    assert result['statement_ids'] == []
    assert len(service.published_statements(consultation)) == len(DRAFTED)


def test_the_embed_flag_endpoint_cannot_reach_a_consultation_statement(app, db, enabled, host, monkeypatch):
    from app.models import StatementFlag

    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]

    response = app.test_client().post(
        '/api/embed/flag',
        json={'statement_id': statement.id, 'flag_reason': 'spam', 'embed_fingerprint': 'abc'},
        headers={'Origin': app.config.get('BASE_URL', 'http://localhost')},
    )

    assert response.status_code == 404
    assert StatementFlag.query.count() == 0


def test_requesting_a_consultation_as_a_discussion_records_nothing(app, db, enabled, host, monkeypatch):
    from app.models import AnalyticsEvent, DiscussionView

    consultation = _live_consultation(host, monkeypatch)
    discussion = consultation.discussion
    browser = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15'}

    visitor = app.test_client()
    assert visitor.get(f'/discussions/{discussion.id}/{discussion.slug}', headers=browser).status_code == 404
    # Exactly what a discussion id that does not exist returns.
    assert visitor.get(f'/discussions/{discussion.id}', headers=browser).status_code == \
        visitor.get('/discussions/999999', headers=browser).status_code

    assert DiscussionView.query.count() == 0
    assert AnalyticsEvent.query.filter_by(discussion_id=discussion.id).count() == 0


def test_signing_in_never_attaches_consultation_votes_even_with_a_forged_fingerprint(app, db, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    client_id = secrets.token_hex(32)
    _vote_all(_participant(app, client_id), consultation, lambda s: 1)
    scoped = hashlib.sha256(f'{client_id}:consultation:{consultation.id}'.encode()).hexdigest()

    assert StatementVote.merge_anonymous_votes(scoped, host.id) == 0
    assert all(v.user_id is None for v in StatementVote.query.all())


def test_a_consultation_with_stray_rows_from_other_features_can_still_be_deleted(app, db, enabled, host, monkeypatch):
    from app.models import DiscussionView, StatementFlag

    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    db.session.add(DiscussionView(discussion_id=consultation.discussion_id, ip_address='203.0.113.9'))
    db.session.add(StatementFlag(statement_id=statement.id, session_fingerprint='f' * 64, flag_reason='spam'))
    db.session.commit()

    service.delete_consultation(consultation)

    assert Consultation.query.count() == 0 and Discussion.query.count() == 0
    assert DiscussionView.query.count() == 0 and StatementFlag.query.count() == 0


# ── Statements: withdrawn, rejected and repeated wording ────────────────────

def test_a_withdrawn_statement_can_be_added_again(app, enabled, host, client, monkeypatch):
    consultation = _draft_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    wording = statement.content
    _login(client, host)

    client.post(f'/consultations/{consultation.id}/statements/{statement.id}/remove')
    response = client.post(f'/consultations/{consultation.id}/statements/add', data={'content': wording})

    assert response.status_code == 302
    assert [s.content for s in service.published_statements(consultation)].count(wording) == 1
    assert Statement.query.filter_by(content=wording).count() == 1


def test_a_statement_can_be_reworded_to_wording_that_was_withdrawn(app, enabled, host, monkeypatch):
    consultation = _draft_consultation(host, monkeypatch)
    first, second = service.published_statements(consultation)[:2]
    wording = first.content
    service.remove_statement(consultation, first.id)

    service.edit_statement(consultation, second.id, wording)

    assert [s.content for s in service.published_statements(consultation)].count(wording) == 1


def test_drafting_again_does_not_bring_back_what_the_host_removed(app, db, enabled, host, monkeypatch):
    consultation = _draft_consultation(host, monkeypatch)
    removed = service.published_statements(consultation)[0]
    service.remove_statement(consultation, removed.id)

    jobs.enqueue_drafting(consultation)
    drain_jobs()

    job = BackgroundJob.query.order_by(BackgroundJob.id.desc()).first()
    assert job.status == BackgroundJob.STATUS_COMPLETED
    assert removed.content not in [s.content for s in service.published_statements(consultation)]


def test_rejected_suggestions_do_not_use_up_the_statement_limit(app, db, enabled, host, monkeypatch):
    app.config['CONSULTATION_MAX_STATEMENTS'] = len(DRAFTED) + 1
    consultation = _live_consultation(host, monkeypatch)
    for n in range(3):
        suggestion = service.add_statement(
            consultation, f'An unwanted suggestion number {n} from the audience.',
            source=service.SOURCE_AUDIENCE, mod_status=ModStatus.PENDING,
        )
        service.reject_statement(consultation, suggestion.id)

    service.add_statement(consultation, 'The host can still add one more statement.')
    # Wording the host rejected is theirs to bring back.
    with pytest.raises(service.ConsultationError):
        service.add_statement(consultation, 'An unwanted suggestion number 0 from the audience.')
    app.config['CONSULTATION_MAX_STATEMENTS'] = len(DRAFTED) + 2
    restored = service.add_statement(consultation, 'An unwanted suggestion number 0 from the audience.')
    assert restored.mod_status == ModStatus.ACCEPTED


def test_the_audience_cannot_resubmit_what_the_host_turned_down(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    wording = 'A suggestion the host decided against using.'
    suggestion = service.add_statement(
        consultation, wording, source=service.SOURCE_AUDIENCE, mod_status=ModStatus.PENDING,
    )
    service.reject_statement(consultation, suggestion.id)

    with pytest.raises(service.ConsultationError):
        service.add_statement(consultation, wording, source=service.SOURCE_AUDIENCE, mod_status=ModStatus.PENDING)
    assert Statement.query.filter_by(content=wording).one().mod_status == ModStatus.REJECTED


# ── Participant privacy and abuse ───────────────────────────────────────────

def test_results_for_participants_withhold_shares_until_enough_people_have_voted(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    consultation.show_results_to_participants = True
    from app import db
    db.session.commit()
    _vote_all(_participant(app), consultation, lambda s: 1)
    second = _participant(app)
    _vote_all(second, consultation, lambda s: -1)

    rows = second.get(f'/c/{consultation.access_token}/results.json').get_json()['results']

    assert rows and all(row['enough_votes'] is False for row in rows)
    assert all(row['agree_share'] is None and row['disagree_share'] is None for row in rows)


def test_a_vote_needs_the_cookie_the_page_sets(app, enabled, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    statement = service.published_statements(consultation)[0]
    url = f'/c/{consultation.access_token}/vote'

    without = app.test_client()
    assert without.post(url, json={'statement_id': statement.id, 'vote': 1}).status_code == 400
    forged = app.test_client()
    forged.set_cookie('ss_voter_client_id', 'not-a-voter-id')
    assert forged.post(url, json={'statement_id': statement.id, 'vote': 1}).status_code == 400

    assert StatementVote.query.count() == 0


def test_participant_and_shared_report_pages_send_no_referrer(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    _vote_all(_participant(app), consultation, lambda s: 1)
    jobs.close_and_report(consultation)
    drain_jobs()
    report = ConsultationReport.query.one()
    report.share()
    from app import db
    db.session.commit()

    page = app.test_client().get(f'/c/{consultation.access_token}')
    shared = app.test_client().get(f'/r/{report.share_token}')

    assert page.headers['Referrer-Policy'] == 'no-referrer'
    assert shared.status_code == 200 and shared.headers['Referrer-Policy'] == 'no-referrer'


# ── Reports across a reopen ─────────────────────────────────────────────────

def _closed_with_report(app, host, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    _vote_all(_participant(app), consultation, lambda s: 1)
    jobs.close_and_report(consultation)
    drain_jobs()
    return consultation


def test_a_shared_link_can_always_be_switched_off(app, db, enabled, host, client, monkeypatch):
    from datetime import timedelta

    consultation = _closed_with_report(app, host, monkeypatch)
    _login(client, host)
    client.post(f'/consultations/{consultation.id}/report/share')
    first = ConsultationReport.query.one()
    token = first.share_token
    assert token

    # Voting reopens and closes again: a newer report now exists.
    service.set_closing_time(consultation, utcnow_naive() + timedelta(days=2))
    jobs.close_and_report(consultation)
    drain_jobs()
    newest = ConsultationReport.query.order_by(ConsultationReport.id.desc()).first()
    assert newest.id != first.id and not newest.is_shared

    page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'still opens an earlier version' in page

    # Sharing the new version keeps the link people already have.
    client.post(f'/consultations/{consultation.id}/report/share')
    db.session.expire_all()
    assert db.session.get(ConsultationReport, newest.id).share_token == token
    assert db.session.get(ConsultationReport, first.id).share_token is None

    client.post(f'/consultations/{consultation.id}/report/unshare')
    assert app.test_client().get(f'/r/{token}').status_code == 404
    assert ConsultationReport.query.filter(ConsultationReport.share_token.isnot(None)).count() == 0


def test_stop_sharing_reaches_a_link_made_for_an_earlier_report(app, db, enabled, host, client, monkeypatch):
    from datetime import timedelta

    consultation = _closed_with_report(app, host, monkeypatch)
    _login(client, host)
    client.post(f'/consultations/{consultation.id}/report/share')
    token = ConsultationReport.query.one().share_token
    service.set_closing_time(consultation, utcnow_naive() + timedelta(days=2))
    jobs.close_and_report(consultation)
    drain_jobs()

    client.post(f'/consultations/{consultation.id}/report/unshare')

    assert app.test_client().get(f'/r/{token}').status_code == 404


def test_after_a_reopen_the_report_page_shows_the_newest_report(app, db, enabled, host, client, monkeypatch):
    from datetime import timedelta

    consultation = _closed_with_report(app, host, monkeypatch)
    service.set_closing_time(consultation, utcnow_naive() + timedelta(days=2))
    _login(client, host)

    stale = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'Voting has reopened since this report was built' in stale

    client.post(f'/consultations/{consultation.id}/report/build')
    drain_jobs()
    page = client.get(f'/consultations/{consultation.id}/report').get_data(as_text=True)
    assert 'This is an interim report' in page


def test_a_failed_report_after_a_reopen_still_produces_a_new_report(app, db, enabled, host, monkeypatch):
    from datetime import timedelta

    consultation = _closed_with_report(app, host, monkeypatch)
    old = ConsultationReport.query.one()
    old.created_at = utcnow_naive() - timedelta(days=3)
    db.session.commit()
    service.set_closing_time(consultation, utcnow_naive() + timedelta(days=2))
    def _fail(job):
        raise RuntimeError('boom')

    from app.lib import job_queue
    monkeypatch.setitem(job_queue._HANDLERS, jobs.JOB_REPORT, _fail)
    job, _created = jobs.enqueue_report(consultation)
    job.max_attempts = 1
    db.session.commit()
    drain_jobs()

    assert db.session.get(BackgroundJob, job.id).status == BackgroundJob.STATUS_DEAD_LETTER
    assert ConsultationReport.query.count() == 2


# ── Limits ──────────────────────────────────────────────────────────────────

def test_deleting_a_consultation_does_not_reset_the_drafting_limit(app, db, enabled, host, monkeypatch):
    app.config['CONSULTATION_DRAFTS_PER_DAY'] = 2
    for _n in range(2):
        consultation = _draft_consultation(host, monkeypatch)
        service.delete_consultation(consultation)

    consultation = service.create_consultation(host, question='One more question to draft for?', organisation_name='Org')
    job, created = jobs.enqueue_drafting(consultation)

    assert job is None and created is False


def test_a_consultation_cannot_be_extended_without_limit(app, enabled, host, client, monkeypatch):
    consultation = _live_consultation(host, monkeypatch)
    _login(client, host)

    for _n in range(3):
        client.post(f'/consultations/{consultation.id}/extend', data={'days': 90})

    from datetime import timedelta
    assert consultation.closes_at <= utcnow_naive() + timedelta(days=service.MAX_OPEN_DAYS)


def test_a_one_day_consultation_is_not_called_quiet_as_soon_as_it_opens(app, db, enabled, host, monkeypatch):
    from datetime import timedelta

    consultation = _live_consultation(host, monkeypatch)
    consultation.closes_at = consultation.published_at + timedelta(days=1)
    db.session.commit()

    jobs.run_sweep()
    assert 'Your consultation closes tomorrow' not in enabled

    consultation.published_at = utcnow_naive() - timedelta(hours=13)
    consultation.closes_at = utcnow_naive() + timedelta(hours=11)
    db.session.commit()
    jobs.run_sweep()
    assert enabled.count('Your consultation closes tomorrow') == 1


def test_one_consultation_in_trouble_does_not_stop_the_sweep(app, db, enabled, host, monkeypatch):
    from datetime import timedelta

    first = _live_consultation(host, monkeypatch)
    second = _live_consultation(host, monkeypatch, question='What should the second consultation ask?')
    for consultation in (first, second):
        consultation.closes_at = utcnow_naive() - timedelta(minutes=1)
    db.session.commit()
    real = jobs.close_and_report

    def _close(consultation):
        if consultation.id == first.id:
            raise RuntimeError('boom')
        return real(consultation)

    monkeypatch.setattr(jobs, 'close_and_report', _close)

    assert jobs.run_sweep()['closed'] == 1
    assert db.session.get(Consultation, second.id).is_closed


def test_rendering_a_report_never_fetches_an_address(app):
    import os
    from app.consultations.pdf import _refuse_unless_local

    static_root = os.path.realpath(app.static_folder)
    _refuse_unless_local('file://' + os.path.join(static_root, 'css', 'report.css'), static_root)
    _refuse_unless_local('data:image/png;base64,AAAA', static_root)
    for url in (
        'https://example.com/pixel.png',
        'http://169.254.169.254/latest/meta-data',
        'file:///etc/passwd',
        'file://' + os.path.join(static_root, '..', 'config.py'),
    ):
        with pytest.raises(ValueError):
            _refuse_unless_local(url, static_root)
