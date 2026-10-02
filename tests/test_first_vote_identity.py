"""A visitor's first vote must be stored under the identity their cookie carries.

A visitor arriving with no cookie (a QR scan, a shared link) is issued a voter
id during the vote request. Every read of that id within the request has to
return the same value, or the vote is stored under one identity and the cookie
is set to another: the first vote stops being "theirs" and one person is
counted as two participants.
"""
import pytest
from flask import session
from flask_wtf.csrf import generate_csrf

from app.lib.vote_identity import (
    VOTER_CANONICAL_COOKIE_NAME,
    fingerprint_from_client_id,
    get_or_create_voter_client_id,
    get_voter_fingerprint,
)
from app.models import DiscussionParticipant, StatementVote
from tests.test_consensus_report_and_export import _create_user, _discussion, _statement


pytestmark = pytest.mark.usefixtures('sqlite_vote_functions')


def _seed(db):
    owner = _create_user(db, 'firstvoteowner', 'firstvoteowner@example.com')
    discussion = _discussion(db, owner.id, title='First Vote Identity Fixture')
    first = _statement(db, discussion.id, owner.id, 'The first statement a visitor sees.')
    second = _statement(db, discussion.id, owner.id, 'The second statement a visitor sees.')
    db.session.commit()
    return discussion.id, first.id, second.id


def _visitor(app):
    """A browser that has loaded a page (session + CSRF token) but never voted."""
    client = app.test_client()
    with app.test_request_context():
        token = generate_csrf()
        raw_token = session['csrf_token']
    with client.session_transaction() as sess:
        sess['csrf_token'] = raw_token
    return client, {'X-CSRFToken': token}


def _cookie_value(client, name):
    cookie = client.get_cookie(name)
    return cookie.value if cookie else None


def test_generated_voter_id_is_stable_within_a_request(app):
    with app.test_request_context('/'):
        first, first_is_new = get_or_create_voter_client_id()
        second, second_is_new = get_or_create_voter_client_id()
        assert first == second
        assert first_is_new and second_is_new
        assert get_voter_fingerprint() == fingerprint_from_client_id(first)

    with app.test_request_context('/'):
        other, _ = get_or_create_voter_client_id()
        assert other != first, 'a generated id must not leak into another request'


def test_first_vote_is_stored_under_the_cookie_the_visitor_receives(app, db):
    discussion_id, first_id, _second_id = _seed(db)
    client, headers = _visitor(app)

    response = client.post(f'/statements/{first_id}/vote', json={'vote': 1}, headers=headers)

    assert response.status_code == 200, response.get_data(as_text=True)
    client_id = _cookie_value(client, VOTER_CANONICAL_COOKIE_NAME)
    assert client_id, 'the vote response must issue the voter cookie'
    vote = StatementVote.query.filter_by(statement_id=first_id).one()
    assert vote.session_fingerprint == fingerprint_from_client_id(client_id)


def test_cookieless_visitor_is_one_participant_across_votes(app, db):
    discussion_id, first_id, second_id = _seed(db)
    client, headers = _visitor(app)

    first = client.post(f'/statements/{first_id}/vote', json={'vote': 1}, headers=headers)
    second = client.post(f'/statements/{second_id}/vote', json={'vote': -1}, headers=headers)

    assert first.status_code == 200 and second.status_code == 200
    assert second.get_json()['user_vote_count'] == 2, (
        'the first vote must still count as this visitor\'s on their second request'
    )
    fingerprints = {
        v.session_fingerprint
        for v in StatementVote.query.filter_by(discussion_id=discussion_id).all()
    }
    assert len(fingerprints) == 1
    assert DiscussionParticipant.query.filter_by(discussion_id=discussion_id).count() == 1


def test_changing_the_first_vote_updates_it_rather_than_adding_a_voter(app, db):
    discussion_id, first_id, _second_id = _seed(db)
    client, headers = _visitor(app)

    client.post(f'/statements/{first_id}/vote', json={'vote': 1}, headers=headers)
    client.post(f'/statements/{first_id}/vote', json={'vote': -1}, headers=headers)

    votes = StatementVote.query.filter_by(statement_id=first_id).all()
    assert [v.vote for v in votes] == [-1]
