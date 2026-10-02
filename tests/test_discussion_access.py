"""One access rule for every route that serves a discussion's data.

Covers the sandbox rule (discussions created with a partner's test API key)
and per-partner embed scoping. Programme visibility itself is covered in
``test_programmes.py``.
"""
import pytest
from flask import g

from app.api.utils import discussion_consensus_url
from app.discussions.access import SANDBOX_KEY_PARAM, sandbox_key_for
from app.lib.time import utcnow_naive
from app.models import Discussion, Partner, PartnerDomain, Programme, Statement, generate_slug
from tests.test_consensus_report_and_export import (
    _analysis,
    _cluster_data,
    _create_user,
    _login,
)


def _partner(db, slug, domain, env='test'):
    partner = Partner(
        name=slug.title(), slug=slug, contact_email=f'{slug}@example.com',
        password_hash='x', status='active', billing_status='active', tier='starter',
    )
    db.session.add(partner)
    db.session.flush()
    db.session.add(PartnerDomain(
        partner_id=partner.id, domain=domain, env=env,
        verification_method='dns_txt', verification_token=f'tok-{slug}',
        verified_at=utcnow_naive(),
    ))
    db.session.flush()
    return partner


def _partner_discussion(db, partner, env='test', title='Sandbox Access Fixture'):
    discussion = Discussion(
        title=title, slug=generate_slug(title), has_native_statements=True,
        geographic_scope='global', partner_env=env,
        partner_id=partner.slug if partner else None,
        partner_fk_id=partner.id if partner else None,
    )
    db.session.add(discussion)
    db.session.flush()
    statement = Statement(
        discussion_id=discussion.id, content='A statement inside the sandbox discussion.',
        is_seed=True, mod_status=1,
    )
    db.session.add(statement)
    db.session.flush()
    _analysis(db, discussion.id, _cluster_data(statement.id, statement.id, statement.id))
    return discussion, statement


@pytest.fixture
def sandbox(app, db):
    owner = _partner(db, 'owner-press', 'owner.example.com')
    other = _partner(db, 'other-press', 'other.example.com')
    discussion, statement = _partner_discussion(db, owner)
    db.session.commit()
    return {
        'owner_id': owner.id, 'other_id': other.id,
        'discussion_id': discussion.id, 'statement_id': statement.id,
        'key': sandbox_key_for(discussion),
    }


def _sandbox_paths(sandbox):
    did, sid = sandbox['discussion_id'], sandbox['statement_id']
    return [
        f'/discussions/{did}/consensus',
        f'/discussions/{did}/consensus/report',
        f'/api/discussions/{did}/consensus/data',
        f'/api/discussions/{did}/consensus/statements',
        f'/api/discussions/{did}/consensus/status',
        f'/api/discussions/{did}/consensus/export',
        f'/api/discussions/{did}/consensus/export?format=csv',
        f'/statements/{sid}',
        f'/api/statements/{sid}/votes',
        f'/discussions/{did}/statements/create',
    ]


def test_sandbox_discussion_is_not_reachable_by_id(sandbox, client):
    for path in _sandbox_paths(sandbox):
        assert client.get(path).status_code == 404, path


def test_sandbox_link_opens_the_analysis_and_is_remembered(sandbox, client):
    did = sandbox['discussion_id']

    opened = client.get(f"/discussions/{did}/consensus?{SANDBOX_KEY_PARAM}={sandbox['key']}")
    assert opened.status_code == 200

    # The page's own data request and onward links carry no key.
    assert client.get(f'/api/discussions/{did}/consensus/data').status_code == 200
    assert client.get(f'/api/discussions/{did}/consensus/export?format=csv').status_code == 200


def test_sandbox_key_only_opens_its_own_discussion(app, db, sandbox, client):
    with app.app_context():
        owner = db.session.get(Partner, sandbox['owner_id'])
        second, _statement = _partner_discussion(db, owner, title='A Second Sandbox Fixture')
        db.session.commit()
        second_id = second.id

    wrong = client.get(f"/discussions/{second_id}/consensus?{SANDBOX_KEY_PARAM}={sandbox['key']}")
    forged = client.get(f"/discussions/{second_id}/consensus?{SANDBOX_KEY_PARAM}=not-a-key")

    assert wrong.status_code == 404
    assert forged.status_code == 404


def test_owning_partner_portal_session_can_open_its_sandbox(sandbox, client):
    with client.session_transaction() as sess:
        sess['partner_portal_id'] = sandbox['owner_id']

    assert client.get(f"/discussions/{sandbox['discussion_id']}/consensus").status_code == 200


def test_another_partner_cannot_open_the_sandbox(sandbox, client):
    with client.session_transaction() as sess:
        sess['partner_portal_id'] = sandbox['other_id']

    assert client.get(f"/discussions/{sandbox['discussion_id']}/consensus").status_code == 404


def test_admin_can_open_a_sandbox_discussion(app, db, sandbox, client):
    with app.app_context():
        admin = _create_user(db, 'sandboxadmin', 'sandboxadmin@example.com')
        admin.is_admin = True
        db.session.commit()
        admin_id = admin.id
    _login(client, admin_id)

    assert client.get(f"/discussions/{sandbox['discussion_id']}/consensus").status_code == 200


def test_embed_token_reads_sandbox_votes_and_a_forged_origin_does_not(app, sandbox, client):
    import json
    import re

    path = f"/api/statements/{sandbox['statement_id']}/votes"
    did = sandbox['discussion_id']
    first_party = app.config.get('BASE_URL', 'https://societyspeaks.io')

    forged = client.application.test_client()
    assert forged.get(
        path, headers={'X-Embed-Request': 'true', 'Origin': first_party},
    ).status_code == 404
    assert forged.get(f'/discussions/{did}/consensus').status_code == 404

    embed = client.get(
        f'/discussions/{did}/embed',
        headers={'Referer': 'https://owner.example.com/article'},
    )
    assert embed.status_code == 200
    match = re.search(r'sandboxEmbedToken: (".*?")', embed.get_data(as_text=True))
    token = json.loads(match.group(1))
    assert token

    # Opening the embed must not authorize later requests by cookie.
    assert client.get(path).status_code == 404
    assert forged.get(path, headers={'X-Sandbox-Embed-Token': token}).status_code == 200
    # The same token does not open the analysis.
    assert forged.get(
        f'/discussions/{did}/consensus',
        headers={'X-Sandbox-Embed-Token': token},
    ).status_code == 404


def test_consensus_url_carries_the_sandbox_key_only_for_sandbox_discussions(app, db, sandbox):
    live, _statement = _partner_discussion(db, None, env='live', title='A Public Fixture')
    db.session.commit()
    sandbox_discussion = db.session.get(Discussion, sandbox['discussion_id'])

    with app.test_request_context():
        sandbox_url = discussion_consensus_url(sandbox_discussion, 'owner-press')
        live_url = discussion_consensus_url(live, 'owner-press')

    assert f"{SANDBOX_KEY_PARAM}={sandbox['key']}" in sandbox_url
    assert 'ref=owner-press' in sandbox_url
    assert SANDBOX_KEY_PARAM not in live_url


def test_embed_link_to_the_analysis_works_for_a_sandbox_discussion(sandbox, client):
    did = sandbox['discussion_id']
    embed = client.get(f'/discussions/{did}/embed', headers={'Referer': 'https://owner.example.com/article'})
    assert embed.status_code == 200
    body = embed.get_data(as_text=True)
    href = body.split('id="consensusLink"')[0].rsplit('href="', 1)[1].split('"', 1)[0]
    path = href.split('societyspeaks.io', 1)[-1].replace('&amp;', '&')

    fresh_browser = client.application.test_client()
    redirected = fresh_browser.get(path)
    assert redirected.status_code == 301
    assert fresh_browser.get(redirected.headers['Location']).status_code == 200


# ── Per-partner embed scoping ───────────────────────────────────────────────

def _frame_ancestors(response):
    csp = response.headers['Content-Security-Policy']
    return csp.split('frame-ancestors', 1)[1].split(';', 1)[0]


def test_partner_discussion_is_frameable_only_by_its_own_partner(sandbox, client):
    did = sandbox['discussion_id']

    from_owner = client.get(f'/discussions/{did}/embed', headers={'Referer': 'https://owner.example.com/a'})
    from_other = client.get(f'/discussions/{did}/embed', headers={'Referer': 'https://other.example.com/a'})

    assert from_owner.status_code == 200
    assert 'https://owner.example.com' in _frame_ancestors(from_owner)
    assert 'https://other.example.com' not in _frame_ancestors(from_owner)
    assert from_other.status_code == 403


def test_public_discussion_is_frameable_by_every_verified_partner(app, db, client):
    _partner(db, 'first-press', 'first.example.com', env='live')
    _partner(db, 'second-press', 'second.example.com', env='live')
    public, _statement = _partner_discussion(db, None, env='live', title='A Public Embed Fixture')
    db.session.commit()

    response = client.get(f'/discussions/{public.id}/embed', headers={'Referer': 'https://first.example.com/a'})

    assert response.status_code == 200
    ancestors = _frame_ancestors(response)
    assert 'https://first.example.com' in ancestors
    assert 'https://second.example.com' in ancestors


def test_legacy_slug_only_discussion_is_scoped_to_its_partner(app, db, client):
    owner = _partner(db, 'legacy-press', 'legacy.example.com', env='live')
    _partner(db, 'rival-press', 'rival.example.com', env='live')
    discussion, _statement = _partner_discussion(db, owner, env='live', title='A Legacy Slug Fixture')
    discussion.partner_fk_id = None
    db.session.commit()

    response = client.get(f'/discussions/{discussion.id}/embed', headers={'Referer': 'https://legacy.example.com/a'})
    rival = client.get(f'/discussions/{discussion.id}/embed', headers={'Referer': 'https://rival.example.com/a'})

    assert response.status_code == 200
    assert 'https://rival.example.com' not in _frame_ancestors(response)
    assert rival.status_code == 403


def test_embed_statement_submission_is_refused_from_another_partners_site(app, db, client):
    owner = _partner(db, 'submit-press', 'submit.example.com', env='live')
    _partner(db, 'intruder-press', 'intruder.example.com', env='live')
    discussion, _statement = _partner_discussion(db, owner, env='live', title='A Submission Fixture')
    discussion.embed_statement_submissions_enabled = True
    db.session.commit()

    response = client.post(
        f'/api/embed/discussions/{discussion.id}/statements',
        json={'content': 'A perfectly reasonable statement to add.'},
        headers={'X-Embed-Request': 'true', 'Origin': 'https://intruder.example.com'},
    )

    assert response.status_code == 403
    assert response.get_json()['error'] == 'origin_not_allowed'


# ── Vote-count cache must not bypass programme visibility ───────────────────

def test_vote_counts_for_a_private_programme_are_not_served_from_cache(app, db, client):
    owner = _create_user(db, 'progowner', 'progowner@example.com')
    programme = Programme(
        name='Private Programme', slug='private-programme', creator_id=owner.id,
        visibility='private', status='active',
    )
    db.session.add(programme)
    db.session.flush()
    discussion = Discussion(
        title='Private Programme Fixture', slug='private-programme-fixture',
        has_native_statements=True, geographic_scope='global',
        creator_id=owner.id, programme_id=programme.id,
    )
    db.session.add(discussion)
    db.session.flush()
    statement = Statement(
        discussion_id=discussion.id, user_id=owner.id,
        content='A statement inside a private programme.',
    )
    db.session.add(statement)
    db.session.commit()
    path = f'/api/statements/{statement.id}/votes'
    owner_id = owner.id

    insider = client.application.test_client()
    _login(insider, owner_id)
    assert insider.get(path).status_code == 200

    # The ``db`` fixture keeps one app context open, so Flask-Login's
    # per-context user would otherwise carry over to the next request.
    g.pop('_login_user', None)
    assert client.get(path).status_code == 403


# ── Published-visible statements only ───────────────────────────────────────

def test_embed_does_not_show_a_statement_rejected_by_moderation(app, db, client):
    public, statement = _partner_discussion(db, None, env='live', title='A Moderated Embed Fixture')
    rejected = Statement(
        discussion_id=public.id, content='This statement was rejected by a moderator.',
        mod_status=-1,
    )
    db.session.add(rejected)
    db.session.commit()

    body = client.get(f'/discussions/{public.id}/embed').get_data(as_text=True)

    assert 'A statement inside the sandbox discussion.' in body
    assert 'rejected by a moderator' not in body


def test_statement_list_url_redirects_to_the_discussion_page(app, db, client):
    public, _statement = _partner_discussion(db, None, env='live', title='A Statement List Fixture')
    db.session.commit()

    response = client.get(f'/discussions/{public.id}/statements?sort=recent')

    assert response.status_code == 301
    assert response.headers['Location'].endswith(
        f'/discussions/{public.id}/{public.slug}?sort=recent'
    )
