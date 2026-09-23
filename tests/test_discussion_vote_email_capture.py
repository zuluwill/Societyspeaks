"""E6: email capture after a discussion vote, not on first paint for new readers."""

import hashlib
import secrets
from pathlib import Path
from unittest.mock import patch

from app.models import (
    DailyBriefSubscriber,
    Discussion,
    Statement,
    StatementVote,
    generate_slug,
)


NATIVE = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'discussions' / 'view_native.html'
CAPTURE = Path(__file__).resolve().parents[1] / 'app' / 'templates' / 'components' / 'email_capture.html'


def _native_discussion(db, title='Capture discussion'):
    discussion = Discussion(
        title=title,
        slug=generate_slug(title),
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()
    statement = Statement(
        discussion_id=discussion.id,
        content='A claim long enough for the statement validation rules.',
        mod_status=1,
        is_deleted=False,
    )
    db.session.add(statement)
    db.session.commit()
    return discussion, statement


def test_capture_is_on_the_discussion_page_and_hidden_until_vote(app, db):
    discussion, _statement = _native_discussion(db)
    client = app.test_client()
    resp = client.get(f'/discussions/{discussion.id}/{discussion.slug}')
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert 'id="discussion-vote-email-capture"' in html
    assert 'data-reveal-on-vote="1"' in html
    assert 'discussion-vote-email-capture' in html
    assert 'hidden' in html
    assert "Get tomorrow's question" in html
    assert 'source" value="discussion_vote"' in html
    assert 'ss:voteRecorded' in html


def test_already_voted_reader_sees_capture_immediately(app, db):
    client_id = secrets.token_hex(32)
    fingerprint = hashlib.sha256(client_id.encode()).hexdigest()
    discussion, statement = _native_discussion(db, title='Already voted capture')
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

    client = app.test_client()
    client.set_cookie('statement_client_id', client_id)
    html = client.get(f'/discussions/{discussion.id}/{discussion.slug}').get_data(as_text=True)
    assert 'id="discussion-vote-email-capture"' in html
    assert 'class="mt-6 rounded-xl border border-primary-200 bg-primary-50 p-5 sm:p-6 hidden"' not in html


def test_brief_subscriber_does_not_see_capture(app, db):
    discussion, _statement = _native_discussion(db, title='Subscriber no capture')
    sub = DailyBriefSubscriber(email='already@example.com', status='active')
    sub.generate_magic_token()
    db.session.add(sub)
    db.session.commit()

    client = app.test_client()
    with client.session_transaction() as sess:
        sess['brief_subscriber_id'] = sub.id
    html = client.get(f'/discussions/{discussion.id}/{discussion.slug}').get_data(as_text=True)
    assert 'id="discussion-vote-email-capture"' not in html


def test_subscribe_inline_from_discussion_vote_creates_subscriber(app, db):
    discussion, _statement = _native_discussion(db, title='Subscribe from vote')
    client = app.test_client()

    with patch('app.lib.bot_protection.check_bot_submission', return_value=False), \
         patch('app.brief.subscription.ResendClient') as mock_client:
        resp = client.post(
            '/brief/subscribe/inline',
            data={
                'email': 'voter@example.com',
                'source': 'discussion_vote',
                'discussion_id': str(discussion.id),
            },
            headers={'X-Requested-With': 'XMLHttpRequest'},
        )

    assert resp.status_code == 200
    data = resp.get_json()
    assert data['success'] is True
    sub = DailyBriefSubscriber.query.filter_by(email='voter@example.com').first()
    assert sub is not None
    assert sub.status == 'active'


def test_native_template_gates_capture_on_flag_not_journey():
    source = NATIVE.read_text(encoding='utf-8')
    assert 'email_capture_after_vote' in source
    assert 'show_email_capture' in source
    capture = CAPTURE.read_text(encoding='utf-8')
    assert 'discussion_vote' in capture
    assert "Get tomorrow's question" in capture
    assert 'ss:voteRecorded' in capture
