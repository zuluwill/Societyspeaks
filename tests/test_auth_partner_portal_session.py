from unittest.mock import patch

from app.lib.time import utcnow_naive


def _create_user(db, email, username="user", password="ValidPass123!"):
    from app.models import User

    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def _create_partner_with_owner(db, email="owner@example.com", slug="team-partner"):
    from app.models import Partner, PartnerMember

    partner = Partner(
        name="Team Partner",
        slug=slug,
        contact_email=email,
        status="active",
        billing_status="inactive",
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


def test_main_login_sets_partner_session_and_nav_for_active_member(app, db):
    from app.models import PartnerMember

    partner, _owner = _create_partner_with_owner(db, email="owner-main@example.com", slug="main-partner")
    member_user = _create_user(db, "member-main@example.com", username="membermain")

    member = PartnerMember(
        partner_id=partner.id,
        email=member_user.email,
        full_name="Member Main",
        role="member",
        status="active",
        accepted_at=utcnow_naive(),
    )
    member.set_password("ValidPass123!")
    db.session.add(member)
    db.session.commit()

    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"email": member_user.email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Partner Portal" in response.data
    with client.session_transaction() as flask_session:
        assert flask_session["partner_portal_id"] == partner.id
        assert flask_session["partner_member_id"] == member.id


def test_main_login_clears_stale_partner_session_for_non_partner_user(app, db):
    stale_partner, stale_owner = _create_partner_with_owner(
        db, email="stale-owner@example.com", slug="stale-partner"
    )
    non_partner_user = _create_user(db, "plain-user@example.com", username="plainuser")

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["partner_portal_id"] = stale_partner.id
        flask_session["partner_member_id"] = stale_owner.id

    response = client.post(
        "/auth/login",
        data={"email": non_partner_user.email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Partner Portal" not in response.data
    with client.session_transaction() as flask_session:
        assert "partner_portal_id" not in flask_session
        assert "partner_member_id" not in flask_session


def test_register_auto_syncs_partner_session_and_replaces_stale_values(app, db):
    stale_partner, stale_owner = _create_partner_with_owner(
        db, email="stale-register-owner@example.com", slug="stale-register-partner"
    )
    register_partner, register_owner = _create_partner_with_owner(
        db, email="new-partner@example.com", slug="fresh-register-partner"
    )

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["captcha_expected"] = 7
        flask_session["partner_portal_id"] = stale_partner.id
        flask_session["partner_member_id"] = stale_owner.id

    with patch("app.auth.routes.send_welcome_email"):
        response = client.post(
            "/auth/register",
            data={
                "username": "freshpartneruser",
                "email": "new-partner@example.com",
                "password": "ValidPass123!",
                "verification": "7",
            },
            follow_redirects=True,
        )

    assert response.status_code == 200
    assert b"Partner Portal" in response.data
    with client.session_transaction() as flask_session:
        assert flask_session["partner_portal_id"] == register_partner.id
        assert flask_session["partner_member_id"] == register_owner.id
