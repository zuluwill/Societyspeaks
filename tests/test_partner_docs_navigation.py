from app.lib.time import utcnow_naive


def _create_partner_with_owner(db, email="docs-owner@example.com", slug="docs-partner"):
    from app.models import Partner, PartnerMember

    partner = Partner(
        name="Docs Partner",
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
        full_name="Docs Owner",
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


def test_api_docs_keeps_public_cta_for_signed_out_users(app, db):
    client = app.test_client()

    response = client.get("/for-publishers/api")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Partner Portal" in body
    assert "Back to dashboard" not in body


def test_api_docs_shows_portal_nav_for_signed_in_partner(app, db):
    partner, owner = _create_partner_with_owner(
        db, email="signed-in-docs@example.com", slug="signed-in-docs"
    )
    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    response = client.get("/for-publishers/api")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Back to dashboard" in body
    assert "Dashboard" in body
    assert "Discussions" in body
    assert "Setup guide" in body
    assert "API docs" in body
    assert "API Reference" in body


def test_api_playground_shows_portal_nav_for_signed_in_partner(app, db):
    partner, owner = _create_partner_with_owner(
        db, email="signed-in-playground@example.com", slug="signed-in-playground"
    )
    client = app.test_client()
    _login_partner_session(client, partner.id, owner.id)

    response = client.get("/for-publishers/api-playground")

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Back to dashboard" in body
    assert "Read API Docs" in body
    assert "Dashboard" in body
    assert "Discussions" in body
    assert "Setup guide" in body
    assert "API docs" in body
