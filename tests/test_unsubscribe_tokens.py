"""Tests for unsubscribe token normalization and URL builders."""

from app.lib.unsubscribe_tokens import (
    build_brief_unsubscribe_url,
    normalize_unsubscribe_token,
    lookup_brief_subscriber_by_unsubscribe_token,
)
from app.models import DailyBriefSubscriber


def test_normalize_unsubscribe_token_strips_noise(app):
    assert normalize_unsubscribe_token('  abc123def>  ') == 'abc123def'


def test_normalize_unsubscribe_token_rejects_none_literal(app):
    assert normalize_unsubscribe_token('None') == ''


def test_lookup_brief_subscriber_by_unsubscribe_token(app, db):
    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='norm@example.com', status='active')
        sub.generate_magic_token()
        sub.ensure_unsubscribe_token()
        db.session.add(sub)
        db.session.commit()
        token = sub.unsubscribe_token

        found = lookup_brief_subscriber_by_unsubscribe_token(f'{token}>')
        assert found is not None
        assert found.id == sub.id


def test_build_brief_unsubscribe_url_uses_stable_token(app, db):
    with app.app_context():
        db.create_all()
        sub = DailyBriefSubscriber(email='build@example.com', status='active')
        sub.generate_magic_token()
        sub.ensure_unsubscribe_token()
        db.session.add(sub)
        db.session.commit()

        url = build_brief_unsubscribe_url('https://societyspeaks.io', sub)
        assert url == f'https://societyspeaks.io/brief/unsubscribe/{sub.unsubscribe_token}'
        assert sub.magic_token not in url
