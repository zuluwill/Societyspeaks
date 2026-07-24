"""Tests for brief magic-link welcome flash behaviour."""

from flask import get_flashed_messages

from app.brief.routes import _flash_brief_magic_link_welcome
from app.models import DailyBriefSubscriber, User


def _seed_brief_user(db, email):
    user = User(email=email, username=email.split('@')[0])
    user.set_password('test-pass-123')
    sub = DailyBriefSubscriber(email=email, status='active', user=user)
    sub.generate_magic_token()
    db.session.add_all([user, sub])
    db.session.commit()
    return sub


def test_flash_helper_skips_prefetch(app, db):
    with app.app_context():
        db.create_all()
        sub = _seed_brief_user(db, 'prefetch@example.com')
        with app.test_request_context(
            '/brief/m/test',
            headers={'Purpose': 'prefetch', 'User-Agent': 'Mozilla/5.0'},
        ):
            _flash_brief_magic_link_welcome(sub)
            assert get_flashed_messages() == []


def test_flash_helper_queues_welcome_for_human_navigation(app, db):
    with app.app_context():
        db.create_all()
        sub = _seed_brief_user(db, 'human@example.com')
        with app.test_request_context(
            '/brief/m/test',
            headers={'User-Agent': 'Mozilla/5.0 (Macintosh)'},
        ):
            _flash_brief_magic_link_welcome(sub)
            assert get_flashed_messages() == [
                'Welcome back! Signed in as human@example.com'
            ]


def test_layout_dedupes_identical_flash_messages(app, db, client):
    with app.app_context():
        db.create_all()

    with client.session_transaction() as sess:
        sess['_flashes'] = [
            ('success', 'Welcome back! Signed in as duplicate@example.com'),
            ('success', 'Welcome back! Signed in as duplicate@example.com'),
        ]

    resp = client.get('/brief/subscribe', follow_redirects=False)
    assert resp.status_code == 200
    assert resp.data.count(b'Welcome back! Signed in as duplicate@example.com') == 1
