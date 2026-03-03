from app.models import (
    Statement,
    StatementVote,
    CompanyProfile,
    Discussion,
    DiscussionParticipant,
    OrganizationMember,
    Programme,
    ProgrammeAccessGrant,
    ProgrammeSteward,
    User,
    generate_slug,
)
from app.programmes.permissions import can_edit_programme, can_steward_programme
from app.programmes.permissions import can_view_programme
from app.programmes.utils import validate_cohort_for_discussion
from app.programmes.routes import get_programme_summary, invalidate_programme_summary_cache


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_programme_creator_can_edit(app, db):
    with app.app_context():
        creator = _create_user(db, 'creator', 'creator@example.com')
        programme = Programme(
            name='National Dialogue',
            slug=generate_slug('National Dialogue'),
            creator_id=creator.id,
        )
        db.session.add(programme)
        db.session.commit()

        assert can_edit_programme(programme, creator) is True


def test_org_editor_can_edit_programme(app, db):
    with app.app_context():
        owner = _create_user(db, 'owner', 'owner@example.com')
        editor = _create_user(db, 'editor', 'editor@example.com')
        company = CompanyProfile(
            user_id=owner.id,
            company_name='Civic Org',
            slug=generate_slug('Civic Org'),
        )
        db.session.add(company)
        db.session.flush()

        membership = OrganizationMember(
            org_id=company.id,
            user_id=editor.id,
            role='editor',
            status='active',
        )
        db.session.add(membership)
        db.session.flush()

        programme = Programme(
            name='Org Programme',
            slug=generate_slug('Org Programme'),
            creator_id=None,
            company_profile_id=company.id,
        )
        db.session.add(programme)
        db.session.commit()

        assert can_edit_programme(programme, editor) is True


def test_org_viewer_and_outsider_cannot_steward_org_programme_without_explicit_steward(app, db):
    with app.app_context():
        owner = _create_user(db, 'orgowner', 'orgowner@example.com')
        viewer = _create_user(db, 'orgviewer', 'orgviewer@example.com')
        outsider = _create_user(db, 'orgoutsider', 'orgoutsider@example.com')
        company = CompanyProfile(
            user_id=owner.id,
            company_name='Civic Org Two',
            slug=generate_slug('Civic Org Two'),
        )
        db.session.add(company)
        db.session.flush()

        membership = OrganizationMember(
            org_id=company.id,
            user_id=viewer.id,
            role='viewer',
            status='active',
        )
        db.session.add(membership)
        db.session.flush()

        programme = Programme(
            name='Org Restricted Programme',
            slug=generate_slug('Org Restricted Programme'),
            creator_id=None,
            company_profile_id=company.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()

        assert can_edit_programme(programme, viewer) is False
        assert can_steward_programme(programme, viewer) is False
        assert can_steward_programme(programme, outsider) is False

        db.session.add(ProgrammeSteward(
            programme_id=programme.id,
            user_id=outsider.id,
            status='active',
        ))
        db.session.commit()
        assert can_steward_programme(programme, outsider) is True


def test_steward_can_export_permissions(app, db):
    with app.app_context():
        creator = _create_user(db, 'creator2', 'creator2@example.com')
        steward_user = _create_user(db, 'steward', 'steward@example.com')
        programme = Programme(
            name='Stewarded Programme',
            slug=generate_slug('Stewarded Programme'),
            creator_id=creator.id,
        )
        db.session.add(programme)
        db.session.flush()

        steward = ProgrammeSteward(
            programme_id=programme.id,
            user_id=steward_user.id,
            status='active',
        )
        db.session.add(steward)
        db.session.commit()

        assert can_steward_programme(programme, steward_user) is True


def test_programme_export_defaults_to_csv_and_supports_json(app, db):
    with app.app_context():
        creator = _create_user(db, 'exportcreator', 'exportcreator@example.com')
        steward_user = _create_user(db, 'exportsteward', 'exportsteward@example.com')
        programme = Programme(
            name='Export Programme',
            slug=generate_slug('Export Programme'),
            creator_id=creator.id,
            visibility='public',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()

        db.session.add(Discussion(
            title='Export discussion one',
            slug=generate_slug('Export discussion one'),
            description='Description long enough for export discussion one.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        ))
        db.session.add(ProgrammeSteward(
            programme_id=programme.id,
            user_id=steward_user.id,
            status='active',
        ))
        db.session.commit()
        programme_slug = programme.slug
        steward_id = steward_user.id

    client = app.test_client()
    _login(client, steward_id)

    csv_resp = client.get(f'/programmes/{programme_slug}/export')
    csv_body = csv_resp.get_data(as_text=True)
    assert csv_resp.status_code == 200
    assert csv_resp.mimetype == 'text/csv'
    assert 'programme_id,programme_slug,programme_name' in csv_body
    assert 'Export discussion one' in csv_body

    json_resp = client.get(f'/programmes/{programme_slug}/export?format=json')
    json_body = json_resp.get_data(as_text=True)
    assert json_resp.status_code == 200
    assert json_resp.mimetype == 'application/json'
    assert '"programme_id"' in json_body


def test_search_discussions_filters_by_programme(app, db):
    with app.app_context():
        creator = _create_user(db, 'searcher', 'searcher@example.com')
        programme = Programme(
            name='Search Programme',
            slug=generate_slug('Search Programme'),
            creator_id=creator.id,
        )
        db.session.add(programme)
        db.session.flush()

        in_programme = Discussion(
            title='In programme discussion',
            slug=generate_slug('In programme discussion'),
            description='Description for in programme discussion long enough.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        )
        outside = Discussion(
            title='Outside discussion',
            slug=generate_slug('Outside discussion'),
            description='Description for outside discussion long enough.',
            creator_id=creator.id,
            geographic_scope='global',
        )
        db.session.add(in_programme)
        db.session.add(outside)
        db.session.commit()

        pagination = Discussion.search_discussions(programme_id=programme.id, page=1, per_page=10)
        ids = [item.id for item in pagination.items]
        assert in_programme.id in ids
        assert outside.id not in ids


def test_validate_cohort_for_discussion(app, db):
    with app.app_context():
        creator = _create_user(db, 'cohortuser', 'cohort@example.com')
        programme = Programme(
            name='Cohort Programme',
            slug=generate_slug('Cohort Programme'),
            creator_id=creator.id,
            cohorts=[{"slug": "pilot", "label": "Pilot"}],
        )
        db.session.add(programme)
        db.session.flush()

        discussion = Discussion(
            title='Cohort discussion',
            slug=generate_slug('Cohort discussion'),
            description='Description for cohort discussion long enough.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        )
        db.session.add(discussion)
        db.session.commit()

        assert validate_cohort_for_discussion(discussion, 'pilot') == 'pilot'
        assert validate_cohort_for_discussion(discussion, 'invalid') is None


def test_mark_information_viewed_tracks_anonymous_participant_and_cohort(app, db):
    with app.app_context():
        creator = _create_user(db, 'infocreator', 'infocreator@example.com')
        programme = Programme(
            name='Info Programme',
            slug=generate_slug('Info Programme'),
            creator_id=creator.id,
            visibility='public',
            status='active',
            cohorts=[{"slug": "pilot", "label": "Pilot"}],
        )
        db.session.add(programme)
        db.session.flush()

        discussion = Discussion(
            title='Info step discussion',
            slug=generate_slug('Info step discussion'),
            description='Description long enough for information step discussion.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
            information_title='Please read first',
            information_body='Important context',
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id

    client = app.test_client()
    response = client.post(f'/discussions/{discussion_id}/information-continue', data={'cohort': 'pilot'})
    assert response.status_code == 302

    with app.app_context():
        participant = DiscussionParticipant.query.filter_by(discussion_id=discussion_id, user_id=None).first()
        assert participant is not None
        assert participant.participant_identifier
        assert participant.viewed_information_at is not None
        assert participant.cohort_slug == 'pilot'


def test_search_page_filters_by_programme_id(app, db):
    with app.app_context():
        creator = _create_user(db, 'searchroute', 'searchroute@example.com')
        programme = Programme(
            name='Route Filter Programme',
            slug=generate_slug('Route Filter Programme'),
            creator_id=creator.id,
        )
        db.session.add(programme)
        db.session.flush()

        in_programme = Discussion(
            title='Route filter included discussion',
            slug=generate_slug('Route filter included discussion'),
            description='Description for included discussion long enough.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        )
        outside = Discussion(
            title='Route filter excluded discussion',
            slug=generate_slug('Route filter excluded discussion'),
            description='Description for excluded discussion long enough.',
            creator_id=creator.id,
            geographic_scope='global',
        )
        db.session.add(in_programme)
        db.session.add(outside)
        db.session.commit()
        programme_id = programme.id

    client = app.test_client()
    response = client.get(f'/discussions/search?programme_id={programme_id}')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Route filter included discussion' in body
    assert 'Route filter excluded discussion' not in body


def test_programme_summary_cache_and_invalidation(app, db):
    with app.app_context():
        creator = _create_user(db, 'summaryuser', 'summary@example.com')
        participant = _create_user(db, 'participantuser', 'participant@example.com')
        programme = Programme(
            name='Summary Programme',
            slug=generate_slug('Summary Programme'),
            creator_id=creator.id,
        )
        db.session.add(programme)
        db.session.flush()

        discussion = Discussion(
            title='Summary discussion one',
            slug=generate_slug('Summary discussion one'),
            description='Description for summary discussion one long enough.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        )
        db.session.add(discussion)
        db.session.flush()

        statement = Statement(
            discussion_id=discussion.id,
            user_id=creator.id,
            content='A valid seed statement with enough length.',
        )
        db.session.add(statement)
        db.session.flush()

        vote_user = StatementVote(
            statement_id=statement.id,
            discussion_id=discussion.id,
            user_id=participant.id,
            vote=1,
        )
        vote_anon = StatementVote(
            statement_id=statement.id,
            discussion_id=discussion.id,
            session_fingerprint='anon-fingerprint-1',
            vote=-1,
        )
        db.session.add(vote_user)
        db.session.add(vote_anon)
        db.session.commit()

        invalidate_programme_summary_cache(programme.id)
        summary_initial = get_programme_summary(programme.id)
        assert summary_initial["discussion_count"] == 1
        assert summary_initial["participant_count"] == 2

        second_discussion = Discussion(
            title='Summary discussion two',
            slug=generate_slug('Summary discussion two'),
            description='Description for summary discussion two long enough.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=programme.id,
        )
        db.session.add(second_discussion)
        db.session.commit()

        # Cached result should still be old until invalidated.
        summary_cached = get_programme_summary(programme.id)
        assert summary_cached["discussion_count"] == 1

        invalidate_programme_summary_cache(programme.id)
        summary_after_invalidate = get_programme_summary(programme.id)
        assert summary_after_invalidate["discussion_count"] == 2


def test_edit_discussion_accepts_valid_programme_theme_phase(app, db):
    with app.app_context():
        creator = _create_user(db, 'editcreator', 'editcreator@example.com')
        programme = Programme(
            name='Edit Programme',
            slug=generate_slug('Edit Programme'),
            creator_id=creator.id,
            themes=['Health'],
            phases=['Phase 1'],
        )
        db.session.add(programme)
        db.session.flush()

        discussion = Discussion(
            title='Editable discussion title',
            slug=generate_slug('Editable discussion title'),
            description='A long enough discussion description for validation.',
            creator_id=creator.id,
            topic='Society',
            geographic_scope='global',
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id
        programme_id = programme.id
        creator_id = creator.id

    client = app.test_client()
    _login(client, creator_id)

    response = client.post(
        f'/discussions/{discussion_id}/edit',
        data={
            'title': 'Editable discussion title updated',
            'description': 'A long enough updated discussion description for validation.',
            'topic': 'Society',
            'keywords': '',
            'geographic_scope': 'global',
            'country': '',
            'city': '',
            'programme_id': str(programme_id),
            'programme_theme': 'Health',
            'programme_phase': 'Phase 1',
            'information_title': '',
            'information_body': '',
            'information_links': '',
        },
        follow_redirects=False,
    )
    assert response.status_code == 302

    with app.app_context():
        updated = db.session.get(Discussion, discussion_id)
        assert updated.programme_id == programme_id
        assert updated.programme_theme == 'Health'
        assert updated.programme_phase == 'Phase 1'


def test_edit_discussion_preserves_city_on_validation_error(app, db):
    with app.app_context():
        creator = _create_user(db, 'editcity', 'editcity@example.com')
        discussion = Discussion(
            title='City editable discussion',
            slug=generate_slug('City editable discussion'),
            description='A long enough discussion description for validation.',
            creator_id=creator.id,
            topic='Society',
            geographic_scope='city',
            country='UK',
            city='London',
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id
        creator_id = creator.id

    client = app.test_client()
    _login(client, creator_id)

    response = client.post(
        f'/discussions/{discussion_id}/edit',
        data={
            'title': 'short',
            'description': 'A long enough updated discussion description for validation.',
            'topic': 'Society',
            'keywords': '',
            'geographic_scope': 'city',
            'country': 'UK',
            'city': 'Leeds',
            'programme_id': '0',
            'programme_theme': '',
            'programme_phase': '',
            'information_title': '',
            'information_body': '',
            'information_links': '',
        },
        follow_redirects=False,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Title must be between 10 and 200 characters' in body
    assert 'value="Leeds" selected' in body


def test_public_programme_catalogue_only_shows_public_live_programmes(app, db):
    with app.app_context():
        creator = _create_user(db, 'catalogue_owner', 'catalogue_owner@example.com')

        public_live = Programme(
            name='Public Live Programme',
            slug=generate_slug('Public Live Programme'),
            creator_id=creator.id,
            visibility='public',
            status='active',
        )
        public_no_discussions = Programme(
            name='Public Empty Programme',
            slug=generate_slug('Public Empty Programme'),
            creator_id=creator.id,
            visibility='public',
            status='active',
        )
        invite_only = Programme(
            name='Invite Programme',
            slug=generate_slug('Invite Programme'),
            creator_id=creator.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add_all([public_live, public_no_discussions, invite_only])
        db.session.flush()

        db.session.add(Discussion(
            title='Public live discussion',
            slug=generate_slug('Public live discussion'),
            description='Description long enough for a public live discussion.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=public_live.id,
            partner_env='live',
            is_closed=False,
        ))
        db.session.add(Discussion(
            title='Invite-only discussion',
            slug=generate_slug('Invite-only discussion'),
            description='Description long enough for an invite-only discussion.',
            creator_id=creator.id,
            geographic_scope='global',
            programme_id=invite_only.id,
            partner_env='live',
            is_closed=False,
        ))
        db.session.commit()

    client = app.test_client()
    response = client.get('/programmes/')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Public Live Programme' in body
    assert 'Public Empty Programme' not in body
    assert 'Invite Programme' not in body


def test_invite_only_programme_requires_explicit_access_grant(app, db):
    with app.app_context():
        owner = _create_user(db, 'programme_owner', 'programme_owner@example.com')
        invited_user = _create_user(db, 'invited_user', 'invited_user@example.com')
        outsider = _create_user(db, 'outsider_user', 'outsider_user@example.com')
        programme = Programme(
            name='Invite Restricted Programme',
            slug=generate_slug('Invite Restricted Programme'),
            creator_id=owner.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()
        db.session.add(Discussion(
            title='Invite restricted discussion',
            slug=generate_slug('Invite restricted discussion'),
            description='Description long enough for invite-restricted discussion.',
            creator_id=owner.id,
            geographic_scope='global',
            programme_id=programme.id,
            partner_env='live',
            is_closed=False,
        ))
        db.session.commit()
        slug = programme.slug
        owner_id = owner.id
        invited_user_id = invited_user.id
        outsider_id = outsider.id
        programme_id = programme.id

    client = app.test_client()
    anon_resp = client.get(f'/programmes/{slug}')
    assert anon_resp.status_code == 404

    _login(client, outsider_id)
    outsider_resp = client.get(f'/programmes/{slug}')
    assert outsider_resp.status_code == 404

    with app.app_context():
        db.session.add(ProgrammeAccessGrant(
            programme_id=programme_id,
            user_id=invited_user_id,
            invited_by_id=owner_id,
            status='active',
        ))
        db.session.commit()

    _login(client, invited_user_id)
    with app.app_context():
        programme = Programme.query.filter_by(slug=slug).first()
        invited_user = db.session.get(User, invited_user_id)
        assert can_view_programme(programme, invited_user) is True


def test_private_programme_denies_non_steward(app, db):
    with app.app_context():
        owner = _create_user(db, 'private_owner', 'private_owner@example.com')
        outsider = _create_user(db, 'private_outsider', 'private_outsider@example.com')
        programme = Programme(
            name='Private Programme',
            slug=generate_slug('Private Programme'),
            creator_id=owner.id,
            visibility='private',
            status='active',
        )
        db.session.add(programme)
        db.session.commit()
        slug = programme.slug
        outsider_id = outsider.id

    client = app.test_client()
    anon_resp = client.get(f'/programmes/{slug}')
    assert anon_resp.status_code == 404

    _login(client, outsider_id)
    outsider_resp = client.get(f'/programmes/{slug}')
    assert outsider_resp.status_code == 404


def test_unlisted_programme_accessible_by_link(app, db):
    with app.app_context():
        creator = _create_user(db, 'unlisted_creator', 'unlisted_creator@example.com')
        programme = Programme(
            name='Unlisted Programme',
            slug=generate_slug('Unlisted Programme'),
            creator_id=creator.id,
            visibility='unlisted',
            status='active',
        )
        db.session.add(programme)
        db.session.commit()
        slug = programme.slug

    client = app.test_client()
    resp = client.get(f'/programmes/{slug}')
    assert resp.status_code == 200


def test_embed_respects_programme_visibility(app, db):
    with app.app_context():
        owner = _create_user(db, 'embed_owner', 'embed_owner@example.com')
        programme = Programme(
            name='Embed Restricted Programme',
            slug=generate_slug('Embed Restricted Programme'),
            creator_id=owner.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()
        discussion = Discussion(
            title='Embed restricted discussion',
            slug=generate_slug('Embed restricted discussion'),
            description='Description long enough for embed-restricted discussion.',
            creator_id=owner.id,
            geographic_scope='global',
            programme_id=programme.id,
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id

    client = app.test_client()
    resp = client.get(f'/discussions/{discussion_id}/embed')
    assert resp.status_code == 403


def test_consensus_view_results_respects_programme_visibility(app, db):
    with app.app_context():
        owner = _create_user(db, 'consensus_owner', 'consensus_owner@example.com')
        programme = Programme(
            name='Consensus Restricted Programme',
            slug=generate_slug('Consensus Restricted Programme'),
            creator_id=owner.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()
        discussion = Discussion(
            title='Consensus restricted discussion',
            slug=generate_slug('Consensus restricted discussion'),
            description='Description long enough for consensus-restricted discussion.',
            creator_id=owner.id,
            geographic_scope='global',
            programme_id=programme.id,
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id

    client = app.test_client()
    resp = client.get(f'/discussions/{discussion_id}/consensus')
    assert resp.status_code == 403


def test_revoked_grant_denies_programme_access(app, db):
    with app.app_context():
        owner = _create_user(db, 'revoke_owner', 'revoke_owner@example.com')
        revoked_user = _create_user(db, 'revoked_user', 'revoked_user@example.com')
        programme = Programme(
            name='Revoke Test Programme',
            slug=generate_slug('Revoke Test Programme'),
            creator_id=owner.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()
        db.session.add(ProgrammeAccessGrant(
            programme_id=programme.id,
            user_id=revoked_user.id,
            invited_by_id=owner.id,
            status='revoked',
        ))
        db.session.commit()
        slug = programme.slug
        revoked_user_id = revoked_user.id

    client = app.test_client()
    _login(client, revoked_user_id)
    resp = client.get(f'/programmes/{slug}')
    assert resp.status_code == 404


def test_private_programme_blocks_participant_invites(app, db):
    with app.app_context():
        owner = _create_user(db, 'private_inviter', 'private_inviter@example.com')
        target = _create_user(db, 'private_target', 'private_target@example.com')
        programme = Programme(
            name='Strict Private Programme',
            slug=generate_slug('Strict Private Programme'),
            creator_id=owner.id,
            visibility='private',
            status='active',
        )
        db.session.add(programme)
        db.session.commit()
        slug = programme.slug
        owner_id = owner.id
        target_id = target.id

    client = app.test_client()
    _login(client, owner_id)
    response = client.post(
        f'/programmes/{slug}/access/invite',
        data={'email': 'private_target@example.com'},
        follow_redirects=True,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Private programmes only allow owner/steward access' in body

    with app.app_context():
        grant = ProgrammeAccessGrant.query.filter_by(user_id=target_id).first()
        assert grant is None


def test_statement_routes_respect_programme_visibility(app, db):
    with app.app_context():
        owner = _create_user(db, 'statement_owner', 'statement_owner@example.com')
        programme = Programme(
            name='Statement Restricted Programme',
            slug=generate_slug('Statement Restricted Programme'),
            creator_id=owner.id,
            visibility='invite_only',
            status='active',
        )
        db.session.add(programme)
        db.session.flush()

        discussion = Discussion(
            title='Statement restricted discussion',
            slug=generate_slug('Statement restricted discussion'),
            description='Description long enough for statement-restricted discussion.',
            creator_id=owner.id,
            geographic_scope='global',
            programme_id=programme.id,
            has_native_statements=True,
        )
        db.session.add(discussion)
        db.session.flush()

        statement = Statement(
            discussion_id=discussion.id,
            user_id=owner.id,
            content='A valid statement with enough length.'
        )
        db.session.add(statement)
        db.session.commit()
        statement_id = statement.id

    client = app.test_client()
    view_resp = client.get(f'/statements/{statement_id}')
    votes_resp = client.get(f'/api/statements/{statement_id}/votes')
    assert view_resp.status_code == 403
    assert votes_resp.status_code == 403
