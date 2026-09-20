"""Unsolicited marketplace/contact-spam filter: block campaigns, keep civic speech."""

from app.lib.content_spam import assess_user_content_spam, is_unsolicited_spam
from app.models import Discussion, Response, Statement, User, generate_slug


ASIAN_THERAPIST_SAMPLE = (
    "WhatsApp(33)754090961 Where to found Top shelf Kazakhstan. "
    "This book details how to finance the resistence. Read *asiantherapist* on "
    "WhatsApp(33)754090961 about how to buying marijuana in #astana, Kazakhstan. "
    "Continue reading *asiantherapist* story on WhatsApp and you'll find out "
    "where to buy 100g of ketamine in #Johor_Bahru, Malaysia. "
    "Contact: Telegram: @Zetherapist Signal: @addsilkroad"
)


def test_blocks_asian_therapist_marketplace_comment():
    verdict = assess_user_content_spam(ASIAN_THERAPIST_SAMPLE)
    assert verdict.blocked is True
    assert verdict.score >= verdict.threshold
    assert 'known_spam_campaign' in verdict.reasons
    assert 'drug_marketplace' in verdict.reasons


def test_blocks_uae_therapist_variant():
    text = (
        "Whatsapp(33)754.090.961,where to buy cocaine online in Dubai, UAE. "
        "Read full story. On Whatsapp(33)754.090.961 the free ebook "
        "*uaetherapist* of how to bought Meth in Riyadh, Saudi Arabia."
    )
    verdict = assess_user_content_spam(text)
    assert verdict.blocked is True
    assert 'known_spam_campaign' in verdict.reasons


def test_allows_civic_whatsapp_mention():
    text = (
        "The council should use WhatsApp to tell residents when bins are collected, "
        "instead of relying on a PDF no one opens."
    )
    assert is_unsolicited_spam(text) is False


def test_allows_drug_policy_without_contact_solicitation():
    text = (
        "I would buy marijuana if it were legalised and taxed, because the current "
        "ban just funds organised crime."
    )
    assert is_unsolicited_spam(text) is False


def test_allows_telegram_used_as_civic_example():
    text = (
        "Telegram channels spread election rumours last year. That is why I want "
        "stronger platform transparency rules, not a ban on messaging apps."
    )
    assert is_unsolicited_spam(text) is False


def test_allows_kazakhstan_geopolitics():
    text = (
        "Kazakhstan's energy policy is relevant here because Europe still buys "
        "oil from the region while talking about diversification."
    )
    assert is_unsolicited_spam(text) is False


def test_blocks_contact_plus_phone_plus_second_channel():
    text = (
        "Message me on WhatsApp +447700900123 or Telegram @dealsdesk if you want "
        "the full list."
    )
    verdict = assess_user_content_spam(text)
    assert verdict.blocked is True
    assert 'contact_channel_with_phone' in verdict.reasons


def test_empty_and_short_civic_text_passes():
    assert is_unsolicited_spam('') is False
    assert is_unsolicited_spam(None) is False
    assert is_unsolicited_spam('I disagree with this statement.') is False


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _seed_discussion(db, *, email_verified=True):
    user = User(
        username='civicuser',
        email='civic@example.com',
        password='hashed',
        email_verified=email_verified,
    )
    db.session.add(user)
    db.session.flush()
    discussion = Discussion(
        title='How should we regulate messaging apps?',
        slug=generate_slug('How should we regulate messaging apps?'),
        creator_id=user.id,
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
        embed_statement_submissions_enabled=True,
    )
    db.session.add(discussion)
    db.session.flush()
    statement = Statement(
        discussion_id=discussion.id,
        user_id=user.id,
        content='Platforms should publish takedown transparency reports.',
        statement_type='claim',
        source='user_submitted',
    )
    db.session.add(statement)
    db.session.commit()
    return user, discussion, statement


def test_create_response_rejects_marketplace_spam(app, db, client):
    user, discussion, statement = _seed_discussion(db)
    _login(client, user.id)

    resp = client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': ASIAN_THERAPIST_SAMPLE,
            'position': 'neutral',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'promotional or unsolicited content' in resp.data
    assert Response.query.filter_by(statement_id=statement.id).count() == 0


def test_create_response_allows_civic_comment(app, db, client):
    user, discussion, statement = _seed_discussion(db)
    _login(client, user.id)

    resp = client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': (
                'I agree, but transparency reports only help if they include '
                'WhatsApp and Telegram, not just the public web.'
            ),
            'position': 'pro',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    created = Response.query.filter_by(statement_id=statement.id).one()
    assert 'transparency reports' in created.content


def test_embed_statement_rejects_marketplace_spam(app, db, client):
    _user, discussion, _statement = _seed_discussion(db)
    resp = client.post(
        f'/api/embed/discussions/{discussion.id}/statements',
        json={
            'content': ASIAN_THERAPIST_SAMPLE[:500],
            'embed_fingerprint': 'spam-fp-1',
        },
        headers={'X-Embed-Request': 'true'},
    )
    assert resp.status_code == 400
    body = resp.get_json()
    assert body['error'] == 'unsolicited_content'
    assert Statement.query.filter_by(discussion_id=discussion.id).count() == 1


def test_embed_statement_allows_civic_claim(app, db, client):
    _user, discussion, _statement = _seed_discussion(db)
    resp = client.post(
        f'/api/embed/discussions/{discussion.id}/statements',
        json={
            'content': 'Local government should consult residents before pedestrianising high streets.',
            'embed_fingerprint': 'civic-fp-1',
        },
        headers={'X-Embed-Request': 'true'},
    )
    assert resp.status_code == 201
    assert Statement.query.filter_by(discussion_id=discussion.id).count() == 2


def test_unverified_user_cannot_post_response(app, db, client):
    user, discussion, statement = _seed_discussion(db, email_verified=False)
    _login(client, user.id)

    resp = client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': 'This is a thoughtful civic argument about platform rules.',
            'position': 'pro',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'verify your email' in resp.data.lower()
    assert Response.query.filter_by(statement_id=statement.id).count() == 0


def test_honeypot_silently_drops_response(app, db, client):
    user, discussion, statement = _seed_discussion(db)
    _login(client, user.id)

    resp = client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': 'This is a thoughtful civic argument about platform rules.',
            'position': 'pro',
            'website_url': 'https://spam.example',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert Response.query.filter_by(statement_id=statement.id).count() == 0


def test_register_honeypot_does_not_create_account(app, db, client):
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7

    resp = client.post(
        '/auth/register',
        data={
            'username': 'honeypotbot',
            'email': 'honeypotbot@example.com',
            'password': 'ValidPass123!',
            'verification': '7',
            'website_url': 'https://spam.example',
        },
        follow_redirects=False,
    )
    assert resp.status_code in (200, 302)
    assert User.query.filter_by(email='honeypotbot@example.com').first() is None


def test_hide_content_spam_command_dry_run_and_apply(app, db):
    user, discussion, statement = _seed_discussion(db)
    spam = Response(
        statement_id=statement.id,
        user_id=user.id,
        position='neutral',
        content=ASIAN_THERAPIST_SAMPLE,
    )
    db.session.add(spam)
    db.session.commit()
    spam_id = spam.id

    runner = app.test_cli_runner()
    dry = runner.invoke(args=['hide-content-spam'])
    assert dry.exit_code == 0
    assert 'Dry-run only' in dry.output
    assert db.session.get(Response, spam_id).is_deleted is False

    applied = runner.invoke(args=['hide-content-spam', '--apply'])
    assert applied.exit_code == 0
    assert db.session.get(Response, spam_id).is_deleted is True
    assert db.session.get(Statement, statement.id).is_deleted is False


def test_honeypot_does_not_flash_fake_success(app, db, client):
    user, discussion, statement = _seed_discussion(db)
    _login(client, user.id)

    client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': 'This is a thoughtful civic argument about platform rules.',
            'position': 'pro',
            'website_url': 'https://spam.example',
        },
        follow_redirects=False,
    )
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes') or []
    assert not any(category == 'success' for category, _message in flashes)


def test_register_honeypot_does_not_flash_welcome(app, db, client):
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7

    client.post(
        '/auth/register',
        data={
            'username': 'honeypotbot2',
            'email': 'honeypotbot2@example.com',
            'password': 'ValidPass123!',
            'verification': '7',
            'website_url': 'https://spam.example',
        },
        follow_redirects=False,
    )
    with client.session_transaction() as sess:
        flashes = sess.get('_flashes') or []
    assert not any('Welcome' in str(message) for _category, message in flashes)
    assert User.query.filter_by(email='honeypotbot2@example.com').first() is None


def test_register_rejects_disposable_email(app, db, client):
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7

    resp = client.post(
        '/auth/register',
        data={
            'username': 'tempbox',
            'email': 'throwaway@mailinator.com',
            'password': 'ValidPass123!',
            'verification': '7',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'lasting email address' in resp.data
    assert User.query.filter_by(email='throwaway@mailinator.com').first() is None


def test_register_turnstile_rejects_missing_token(app, db, client):
    app.config['TURNSTILE_SITE_KEY'] = 'test-site-key'
    app.config['TURNSTILE_SECRET_KEY'] = 'test-secret-key'

    resp = client.post(
        '/auth/register',
        data={
            'username': 'turnstilebot',
            'email': 'turnstilebot@example.com',
            'password': 'ValidPass123!',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'human verification' in resp.data
    assert User.query.filter_by(email='turnstilebot@example.com').first() is None


def test_register_turnstile_accepts_verified_token(app, db, client, monkeypatch):
    app.config['TURNSTILE_SITE_KEY'] = 'test-site-key'
    app.config['TURNSTILE_SECRET_KEY'] = 'test-secret-key'
    monkeypatch.setattr(
        'app.lib.bot_protection.verify_turnstile_token',
        lambda *args, **kwargs: True,
    )

    resp = client.post(
        '/auth/register',
        data={
            'username': 'turnstileok',
            'email': 'turnstileok@example.com',
            'password': 'ValidPass123!',
            'cf-turnstile-response': 'ok-token',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert User.query.filter_by(email='turnstileok@example.com').first() is not None


def test_register_page_falls_back_to_math_captcha(app, db, client):
    resp = client.get('/auth/register')
    assert resp.status_code == 200
    assert b'verification' in resp.data
    assert b'cf-turnstile' not in resp.data


def test_unverified_user_statement_hourly_limit(app, db, client):
    user = User(
        username='newunverified',
        email='newunverified@example.com',
        password='hashed',
        email_verified=False,
    )
    db.session.add(user)
    db.session.flush()
    discussion = Discussion(
        title='How should cities plan housing?',
        slug=generate_slug('How should cities plan housing?'),
        creator_id=user.id,
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.commit()
    _login(client, user.id)

    for index in range(2):
        resp = client.post(
            f'/discussions/{discussion.id}/statements/create',
            data={
                'content': f'Civic housing idea number {index} about density near transit.',
                'statement_type': 'claim',
            },
            follow_redirects=False,
        )
        assert resp.status_code == 302

    assert Statement.query.filter_by(discussion_id=discussion.id, is_deleted=False).count() == 2

    resp = client.post(
        f'/discussions/{discussion.id}/statements/create',
        data={
            'content': 'A third civic housing idea should wait until the hour resets.',
            'statement_type': 'claim',
        },
        follow_redirects=True,
    )
    assert resp.status_code == 200
    assert b'new or unverified accounts' in resp.data.lower()
    assert Statement.query.filter_by(discussion_id=discussion.id, is_deleted=False).count() == 2


def test_anonymous_civic_statement_still_allowed(app, db, client):
    _user, discussion, _statement = _seed_discussion(db)
    resp = client.post(
        f'/discussions/{discussion.id}/statements/create',
        data={
            'content': 'Residents should be asked before a high street is pedestrianised.',
            'statement_type': 'claim',
        },
        follow_redirects=False,
    )
    assert resp.status_code == 302
    assert Statement.query.filter_by(discussion_id=discussion.id, is_deleted=False).count() == 2


def test_blocked_spam_records_canonical_event(app, db, client):
    from app.models import AnalyticsEvent

    user, discussion, statement = _seed_discussion(db)
    _login(client, user.id)

    client.post(
        f'/statements/{statement.id}/responses/create',
        data={
            'content': ASIAN_THERAPIST_SAMPLE,
            'position': 'neutral',
        },
        follow_redirects=True,
    )
    events = AnalyticsEvent.query.filter_by(event_name='content_spam_blocked').all()
    assert len(events) == 1
    assert events[0].discussion_id == discussion.id
    assert events[0].event_metadata.get('score') >= 6


def test_turnstile_unconfigured_allows_submission(app):
    from app.lib.bot_protection import turnstile_is_configured, verify_turnstile_token
    app.config['TURNSTILE_SITE_KEY'] = ''
    app.config['TURNSTILE_SECRET_KEY'] = ''
    assert turnstile_is_configured() is False
    assert verify_turnstile_token(None) is True


def test_content_spam_spike_pages_ops(app, monkeypatch):
    alerts = []
    fake_redis = type('R', (), {})()
    fake_redis.incr = lambda key: 8
    fake_redis.expire = lambda key, ttl: None
    monkeypatch.setattr('app.lib.redis_client.get_client', lambda **kw: fake_redis)
    monkeypatch.setattr('app.scheduler._send_ops_alert', lambda message: alerts.append(message))
    app.config['CONTENT_SPAM_ALERT_THRESHOLD'] = 8

    from app.lib.spam_telemetry import record_content_spam_block
    with app.app_context():
        record_content_spam_block(
            context='statement',
            score=12,
            reasons=('known_spam_campaign',),
            discussion_id=1,
        )
    assert alerts
    assert 'spiked' in alerts[0]


def test_admin_can_hide_matching_spam(app, db, client):
    user, discussion, statement = _seed_discussion(db)
    user.is_admin = True
    spam = Response(
        statement_id=statement.id,
        user_id=user.id,
        position='neutral',
        content=ASIAN_THERAPIST_SAMPLE,
    )
    db.session.add(spam)
    db.session.commit()
    spam_id = spam.id
    _login(client, user.id)

    preview = client.post(
        '/admin/moderation/hide-content-spam',
        follow_redirects=True,
    )
    assert preview.status_code == 200
    assert b'Preview' in preview.data
    assert db.session.get(Response, spam_id).is_deleted is False

    applied = client.post(
        '/admin/moderation/hide-content-spam',
        data={'apply': '1'},
        follow_redirects=True,
    )
    assert applied.status_code == 200
    assert db.session.get(Response, spam_id).is_deleted is True
