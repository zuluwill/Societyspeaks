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
