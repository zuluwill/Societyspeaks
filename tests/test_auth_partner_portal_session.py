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


def test_partner_only_account_can_log_in_via_main_login_and_clears_old_session(app, db):
    partner, owner = _create_partner_with_owner(
        db, email="PartnerOnly@example.com", slug="partner-only-main-login"
    )

    client = app.test_client()
    with client.session_transaction() as flask_session:
        flask_session["prelogin_marker"] = "stale"

    response = client.post(
        "/auth/login",
        data={"email": "  PARTNERONLY@example.com  ", "password": "ValidPass123!"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/for-publishers/portal/dashboard")
    with client.session_transaction() as flask_session:
        assert flask_session["partner_portal_id"] == partner.id
        assert flask_session["partner_member_id"] == owner.id
        assert "prelogin_marker" not in flask_session


def test_partner_only_login_rejects_inactive_member_even_if_partner_password_matches(app, db):
    partner, owner = _create_partner_with_owner(
        db, email="inactive-owner@example.com", slug="inactive-partner-login"
    )
    owner.status = "disabled"
    db.session.commit()

    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"email": partner.contact_email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Invalid email or password." in response.data
    with client.session_transaction() as flask_session:
        assert "partner_portal_id" not in flask_session
        assert "partner_member_id" not in flask_session


def test_partner_only_main_login_creates_owner_member_and_updates_last_login(app, db):
    from app.models import Partner, PartnerMember

    partner = Partner(
        name="Legacy Partner",
        slug="legacy-partner-main-login",
        contact_email="legacy-partner@example.com",
        status="active",
        billing_status="inactive",
    )
    partner.set_password("ValidPass123!")
    db.session.add(partner)
    db.session.commit()

    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"email": "legacy-partner@example.com", "password": "ValidPass123!"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/for-publishers/portal/dashboard")

    owner = PartnerMember.query.filter_by(
        partner_id=partner.id,
        email=partner.contact_email,
    ).first()
    assert owner is not None
    assert owner.role == "owner"
    assert owner.status == "active"
    assert owner.last_login_at is not None

    with client.session_transaction() as flask_session:
        assert flask_session["partner_portal_id"] == partner.id
        assert flask_session["partner_member_id"] == owner.id


def test_partner_lockout_is_shared_between_main_login_and_portal_login(app, db):
    partner, _owner = _create_partner_with_owner(
        db, email="shared-lockout@example.com", slug="shared-lockout-partner"
    )
    client = app.test_client()

    for _ in range(5):
        client.post(
            "/auth/login",
            data={"email": partner.contact_email, "password": "WrongPass123!"},
            follow_redirects=True,
        )

    response = client.post(
        "/for-publishers/portal/login",
        data={"email": partner.contact_email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"Too many failed attempts." in response.data


def test_partner_lockout_message_is_shown_when_main_login_triggers_lockout(app, db):
    partner, _owner = _create_partner_with_owner(
        db, email="main-lockout@example.com", slug="main-lockout-partner"
    )
    client = app.test_client()

    response = None
    for _ in range(5):
        response = client.post(
            "/auth/login",
            data={"email": partner.contact_email, "password": "WrongPass123!"},
            follow_redirects=True,
        )

    assert response is not None
    assert response.status_code == 200
    assert b"Too many failed attempts." in response.data


def test_main_login_shows_deactivated_message_for_inactive_partner_member_without_lockout(app, db):
    from app.lib.partner_portal_session import partner_login_lockout_key

    partner, owner = _create_partner_with_owner(
        db, email="inactive-partner-owner@example.com", slug="inactive-partner-owner"
    )
    partner.status = "inactive"
    owner.status = "active"
    db.session.commit()

    client = app.test_client()
    response = client.post(
        "/auth/login",
        data={"email": partner.contact_email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"This account has been deactivated. Please contact support." in response.data
    with client.session_transaction() as flask_session:
        assert "partner_portal_id" not in flask_session
        assert "partner_member_id" not in flask_session
        assert partner_login_lockout_key(partner.contact_email) not in flask_session
        assert f"{partner_login_lockout_key(partner.contact_email)}:until" not in flask_session


def test_portal_login_shows_deactivated_message_for_inactive_partner_member_without_lockout(app, db):
    from app.lib.partner_portal_session import partner_login_lockout_key

    partner, owner = _create_partner_with_owner(
        db, email="inactive-portal-owner@example.com", slug="inactive-portal-owner"
    )
    partner.status = "inactive"
    owner.status = "active"
    db.session.commit()

    client = app.test_client()
    response = client.post(
        "/for-publishers/portal/login",
        data={"email": partner.contact_email, "password": "ValidPass123!"},
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"This account has been deactivated. Please contact support." in response.data
    with client.session_transaction() as flask_session:
        assert "partner_portal_id" not in flask_session
        assert "partner_member_id" not in flask_session
        assert partner_login_lockout_key(partner.contact_email) not in flask_session
        assert f"{partner_login_lockout_key(partner.contact_email)}:until" not in flask_session
