from datetime import datetime, timezone
from unittest.mock import patch

from app.lib.time import utcnow_naive


def _create_partner_with_owner(db, email="owner-discussions@example.com"):
    from app.models import Partner, PartnerMember

    partner = Partner(
        name="Portal Discussions Partner",
        slug=f"portal-discussions-{email.split('@')[0]}",
        contact_email=email,
        password_hash="fakehash",
        status="active",
        billing_status="active",
        tier="starter",
    )
    partner.set_password("ValidPass123!")
    db.session.add(partner)
    db.session.flush()

    owner = PartnerMember(
        partner_id=partner.id,
        email=email,
        full_name="Owner User",
        role="owner",
        status="active",
        accepted_at=utcnow_naive(),
    )
    owner.set_password("ValidPass123!")
    db.session.add(owner)
    db.session.commit()
    return partner, owner


def _login_partner_session(client, partner_id, member_id):
    with client.session_transaction() as flask_session:
        flask_session["partner_portal_id"] = partner_id
        flask_session["partner_member_id"] = member_id


def test_check_partner_quota_live_uses_utc_now(app, db, monkeypatch):
    partner, _ = _create_partner_with_owner(db, email="quota-utc@example.com")
    captured = {"tz": None}

    class FakeDateTime:
        @classmethod
        def now(cls, tz=None):
            captured["tz"] = tz
            return datetime(2026, 4, 8, 10, 0, 0, tzinfo=timezone.utc)

    monkeypatch.setattr("app.partner.routes.datetime", FakeDateTime)

    from app.partner.routes import _check_partner_quota_for_env

    with app.app_context():
        assert _check_partner_quota_for_env(partner, "live") is None

    assert captured["tz"] == timezone.utc


def test_portal_create_discussion_rejects_overlong_article_url(app, db):
    from app.models import Discussion

    partner, owner = _create_partner_with_owner(db, email="long-url@example.com")
    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    too_long_url = "https://example.com/" + ("a" * 2100)
    response = client.post(
        "/for-publishers/portal/discussions/new",
        data={
            "title": "Long URL Test",
            "article_url": too_long_url,
            "env": "test",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    created = Discussion.query.filter_by(partner_fk_id=partner.id, title="Long URL Test").first()
    assert created is None


def test_portal_create_discussion_truncates_excerpt_for_seed_generation_and_sets_ai_source(app, db):
    from app.models import Discussion

    partner, owner = _create_partner_with_owner(db, email="seed-source@example.com")
    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    seen = {"excerpt": None}

    def _fake_generate_seed_statements_from_content(*, title, excerpt, source_name):
        seen["excerpt"] = excerpt
        return [{"content": "This is a generated seed statement.", "position": "neutral"}]

    with patch(
        "app.trending.seed_generator.generate_seed_statements_from_content",
        side_effect=_fake_generate_seed_statements_from_content,
    ):
        response = client.post(
            "/for-publishers/portal/discussions/new",
            data={
                "title": "Seed Generation Test",
                "external_id": "seed-source-1",
                "excerpt": "x" * 6000,
                "env": "test",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert seen["excerpt"] is not None
    assert len(seen["excerpt"]) == 5000

    discussion = Discussion.query.filter_by(partner_fk_id=partner.id, title="Seed Generation Test").first()
    assert discussion is not None
    assert len(discussion.statements) == 1
    assert discussion.statements[0].source == "ai_generated"


def test_portal_add_statement_invalidates_snapshot_cache_and_sets_source(app, db):
    from app.models import Discussion, Statement

    partner, owner = _create_partner_with_owner(db, email="add-statement@example.com")
    discussion = Discussion(
        title="Portal Add Statement",
        slug="portal-add-statement",
        has_native_statements=True,
        partner_id=partner.slug,
        partner_fk_id=partner.id,
        partner_env="test",
    )
    db.session.add(discussion)
    db.session.commit()

    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    with patch("app.partner.routes.invalidate_partner_snapshot_cache") as invalidate_mock:
        response = client.post(
            f"/for-publishers/portal/discussions/{discussion.id}/statements/new",
            data={"content": "This is a partner-provided statement from portal.", "stance": "neutral"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    created = Statement.query.filter_by(discussion_id=discussion.id, is_deleted=False).first()
    assert created is not None
    assert created.source == "partner_provided"
    invalidate_mock.assert_called_once_with(discussion.id)


def test_portal_add_statement_enforces_max_statement_cap(app, db):
    from app.models import Discussion, Statement

    partner, owner = _create_partner_with_owner(db, email="statement-cap@example.com")
    discussion = Discussion(
        title="Portal Statement Cap",
        slug="portal-statement-cap",
        has_native_statements=True,
        partner_id=partner.slug,
        partner_fk_id=partner.id,
        partner_env="test",
    )
    db.session.add(discussion)
    db.session.flush()
    db.session.add(
        Statement(
            discussion_id=discussion.id,
            content="This is an existing seed statement at cap.",
            statement_type="claim",
            is_seed=True,
            mod_status=1,
            source="partner_provided",
        )
    )
    db.session.commit()

    app.config["MAX_STATEMENTS_PER_DISCUSSION"] = 1
    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    with patch("app.partner.routes.invalidate_partner_snapshot_cache") as invalidate_mock:
        response = client.post(
            f"/for-publishers/portal/discussions/{discussion.id}/statements/new",
            data={"content": "This statement should be blocked by max cap.", "stance": "pro"},
            follow_redirects=False,
        )

    assert response.status_code == 302
    statements = Statement.query.filter_by(discussion_id=discussion.id, is_deleted=False).all()
    assert len(statements) == 1
    invalidate_mock.assert_not_called()
