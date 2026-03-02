from app.models import (
    Statement,
    StatementVote,
    CompanyProfile,
    Discussion,
    OrganizationMember,
    Programme,
    ProgrammeSteward,
    User,
    generate_slug,
)
from app.programmes.permissions import can_edit_programme, can_steward_programme
from app.programmes.utils import validate_cohort_for_discussion
from app.programmes.routes import get_programme_summary, invalidate_programme_summary_cache


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


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
