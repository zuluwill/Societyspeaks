"""
Regression tests for briefing auto-recipient identity fields.
"""


def _create_user(db, username, email, is_admin=True):
    from app.models import User

    user = User(
        username=username,
        email=email,
        password='hashed-password',
        is_admin=is_admin,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login(client, user_id):
    with client.session_transaction() as session:
        session['_user_id'] = str(user_id)
        session['_fresh'] = True


def test_create_briefing_auto_recipient_uses_username(app, db):
    from app.models import BriefRecipient, Briefing

    with app.app_context():
        user = _create_user(db, 'create_route_user', 'create_route_user@example.com')
        user_id = user.id
        user_email = user.email
        user_username = user.username

    client = app.test_client()
    _login(client, user_id)

    response = client.post(
        '/briefings/create',
        data={
            'name': 'Create Route Briefing',
            'description': 'Created from direct route',
            'owner_type': 'user',
            'cadence': 'daily',
            'timezone': 'UTC',
            'preferred_send_hour': '9',
            'preferred_send_minute': '0',
            'mode': 'auto_send',
            'visibility': 'private',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        briefing = Briefing.query.filter_by(name='Create Route Briefing').first()
        assert briefing is not None

        recipient = BriefRecipient.query.filter_by(
            briefing_id=briefing.id,
            email=user_email,
        ).first()
        assert recipient is not None
        assert recipient.name == user_username


def test_use_template_auto_recipient_uses_username(app, db):
    from app.models import BriefRecipient, BriefTemplate, Briefing

    with app.app_context():
        user = _create_user(db, 'template_route_user', 'template_route_user@example.com')
        template = BriefTemplate(
            name='Auto Recipient Template',
            description='Template for recipient identity test',
            is_active=True,
            default_sources=[],
        )
        db.session.add(template)
        db.session.commit()
        user_id = user.id
        user_email = user.email
        user_username = user.username
        template_id = template.id

    client = app.test_client()
    _login(client, user_id)

    response = client.post(
        f'/briefings/template/{template_id}/use',
        data={
            'name': 'Template Route Briefing',
            'description': 'Created from template route',
            'owner_type': 'user',
            'cadence': 'daily',
            'timezone': 'UTC',
            'preferred_send_hour': '10',
            'preferred_send_minute': '0',
            'mode': 'auto_send',
            'visibility': 'private',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302

    with app.app_context():
        briefing = Briefing.query.filter_by(
            name='Template Route Briefing',
            theme_template_id=template_id,
        ).first()
        assert briefing is not None

        recipient = BriefRecipient.query.filter_by(
            briefing_id=briefing.id,
            email=user_email,
        ).first()
        assert recipient is not None
        assert recipient.name == user_username


def test_add_auto_recipient_helper_persists_username(app_context):
    from types import SimpleNamespace
    from unittest.mock import patch
    from app.briefing.routes import add_auto_recipient_for_user

    briefing = SimpleNamespace(id=123)
    user = SimpleNamespace(email='helper_user@example.com', username='helper_user')

    with patch('app.briefing.routes.BriefRecipient') as mock_recipient_cls, patch('app.briefing.routes.db') as mock_db:
        mock_recipient = mock_recipient_cls.return_value
        result = add_auto_recipient_for_user(briefing, user)

        mock_recipient_cls.assert_called_once_with(
            briefing_id=briefing.id,
            email=user.email,
            name=user.username,
            status='active',
        )
        mock_recipient.generate_magic_token.assert_called_once()
        mock_db.session.add.assert_called_once_with(mock_recipient)
        assert result is mock_recipient
