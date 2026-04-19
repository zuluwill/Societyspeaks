import hashlib
import secrets

from flask_login import login_user

from app.api.utils import get_discussion_participant_count
from app.discussions.consensus import build_consensus_ui_state
from app.discussions import statements as statements_module
from app.models import Discussion, Statement, StatementVote, User, generate_slug


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def test_participant_count_can_exclude_deleted_statement_votes(app, db):
    with app.app_context():
        user_active = _create_user(db, 'activevoter', 'active@example.com')
        user_deleted = _create_user(db, 'deletedvoter', 'deleted@example.com')

        discussion = Discussion(
            title='Participant Count Consistency',
            slug=generate_slug('Participant Count Consistency'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()

        active_statement = Statement(
            discussion_id=discussion.id,
            user_id=user_active.id,
            content='Active statement for counting participants.',
            is_deleted=False,
        )
        deleted_statement = Statement(
            discussion_id=discussion.id,
            user_id=user_deleted.id,
            content='Deleted statement should not count in filtered mode.',
            is_deleted=True,
        )
        db.session.add(active_statement)
        db.session.add(deleted_statement)
        db.session.flush()

        db.session.add_all([
            StatementVote(
                statement_id=active_statement.id,
                discussion_id=discussion.id,
                user_id=user_active.id,
                vote=1,
            ),
            StatementVote(
                statement_id=deleted_statement.id,
                discussion_id=discussion.id,
                user_id=user_deleted.id,
                vote=-1,
            ),
            StatementVote(
                statement_id=active_statement.id,
                discussion_id=discussion.id,
                session_fingerprint='anon-active-fingerprint',
                vote=0,
            ),
            StatementVote(
                statement_id=deleted_statement.id,
                discussion_id=discussion.id,
                session_fingerprint='anon-deleted-fingerprint',
                vote=1,
            ),
        ])
        db.session.commit()

        include_deleted = get_discussion_participant_count(
            discussion,
            include_deleted_statement_votes=True,
        )
        exclude_deleted = get_discussion_participant_count(
            discussion,
            include_deleted_statement_votes=False,
        )

        assert include_deleted == 4
        assert exclude_deleted == 2


def test_non_native_discussion_route_does_not_call_consensus_ui_builder(app, db, monkeypatch):
    with app.app_context():
        discussion = Discussion(
            title='Polis Embed Discussion',
            slug=generate_slug('Polis Embed Discussion'),
            has_native_statements=False,
            embed_code='<div>embed</div>',
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id = discussion.id
        discussion_slug = discussion.slug

    def _should_not_be_called(_discussion, *_args, **_kwargs):
        raise AssertionError("build_consensus_ui_state should not run for non-native discussions")

    monkeypatch.setattr('app.discussions.routes.build_consensus_ui_state', _should_not_be_called)
    client = app.test_client()
    response = client.get(f'/discussions/{discussion_id}/{discussion_slug}')
    assert response.status_code == 200


def test_consensus_ui_state_hides_moderated_statements_for_non_owner(app, db):
    with app.app_context():
        discussion = Discussion(
            title='Moderation Scoped Consensus Metrics',
            slug=generate_slug('Moderation Scoped Consensus Metrics'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()

        approved = Statement(
            discussion_id=discussion.id,
            content='Approved statement',
            mod_status=1,
            is_deleted=False,
            vote_count_agree=3,
            vote_count_disagree=1,
            vote_count_unsure=0,
        )
        moderated = Statement(
            discussion_id=discussion.id,
            content='Hidden statement',
            mod_status=-1,
            is_deleted=False,
            vote_count_agree=50,
            vote_count_disagree=25,
            vote_count_unsure=10,
        )
        db.session.add(approved)
        db.session.add(moderated)
        db.session.commit()

        with app.test_request_context('/'):
            state = build_consensus_ui_state(discussion)

        assert state['consensus_progress']['statement_count'] == 1
        assert state['consensus_progress']['total_votes'] == 4


def test_build_consensus_ui_state_unlocks_for_site_admin_without_votes(app, db):
    """Site admins bypass the participation gate (same as consensus view_results)."""
    with app.app_context():
        creator = _create_user(db, 'creatoradm', 'creatoradm@example.com')
        admin = _create_user(db, 'siteadminui', 'siteadminui@example.com')
        admin.is_admin = True
        db.session.flush()
        discussion = Discussion(
            title='Admin UI unlock',
            slug=generate_slug('Admin UI unlock'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
            creator_id=creator.id,
        )
        db.session.add(discussion)
        db.session.commit()

        with app.test_request_context('/'):
            login_user(admin)
            state = build_consensus_ui_state(discussion)

        assert state['user_vote_count'] == 0
        assert state['is_consensus_unlocked'] is True


def test_idempotency_cached_response_survives_ui_refresh_failure(app, db, monkeypatch):
    with app.app_context():
        discussion = Discussion(
            title='Idempotency Guard',
            slug=generate_slug('Idempotency Guard'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        statement = Statement(
            discussion_id=discussion.id,
            content='Statement for idempotency test.',
            mod_status=1,
            is_deleted=False,
        )
        db.session.add(statement)
        db.session.commit()
        statement_id = statement.id

    cached_payload = {
        'success': True,
        'vote': 1,
        'vote_count_agree': 1,
        'vote_count_disagree': 0,
        'vote_count_unsure': 0,
        'total_votes': 1,
        'agreement_rate': 1.0,
        'controversy_score': 0.0,
    }
    request_hash = statements_module._vote_request_hash(1, 3, None, None)

    def _fake_cache_get(_key):
        return {
            'request_hash': request_hash,
            'response': cached_payload,
            'status_code': 200,
        }

    def _should_not_persist(**_kwargs):
        raise AssertionError("Vote persistence should not run for idempotent replay")

    def _ui_refresh_failure(_discussion):
        raise RuntimeError("simulated ui refresh failure")

    monkeypatch.setattr('app.discussions.statements.cache.get', _fake_cache_get)
    monkeypatch.setattr('app.discussions.statements._persist_vote_with_upsert', _should_not_persist)
    monkeypatch.setattr('app.discussions.consensus.build_consensus_ui_state', _ui_refresh_failure)

    client = app.test_client()
    response = client.post(
        f'/statements/{statement_id}/vote',
        json={'vote': 1},
        headers={
            'Idempotency-Key': 'same-key',
            'X-Embed-Request': 'true',
        },
    )

    assert response.status_code == 200
    data = response.get_json()
    assert data['success'] is True
    assert data['vote'] == 1


def test_anonymous_discussion_page_seeds_vote_buttons_from_fingerprint_cookie(app, db):
    """Gated footer + selected vote must match DB for anonymous users (not only logged-in)."""
    client_id = secrets.token_hex(32)
    fingerprint = hashlib.sha256(client_id.encode()).hexdigest()

    with app.app_context():
        discussion = Discussion(
            title='Anon vote seed discussion',
            slug=generate_slug('Anon vote seed discussion'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        statement = Statement(
            discussion_id=discussion.id,
            content='Statement long enough for validation rules.',
            mod_status=1,
            is_deleted=False,
        )
        db.session.add(statement)
        db.session.flush()
        db.session.add(
            StatementVote(
                statement_id=statement.id,
                discussion_id=discussion.id,
                user_id=None,
                session_fingerprint=fingerprint,
                vote=1,
            )
        )
        db.session.commit()
        discussion_id = discussion.id
        discussion_slug = discussion.slug

    client = app.test_client()
    client.set_cookie('statement_client_id', client_id)
    response = client.get(f'/discussions/{discussion_id}/{discussion_slug}')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'data-vote-selected="1"' in html
    assert 'Vote to see results' not in html
    assert 'total votes' in html
