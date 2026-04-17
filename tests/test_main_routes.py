def test_platform_route_renders_for_anonymous_user(app, db):
    client = app.test_client()
    response = client.get('/platform')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Nuanced debate.' in body
    assert 'Discussions &amp; Programmes' in body


def test_platform_route_exposes_primary_ctas(app, db):
    client = app.test_client()
    response = client.get('/platform')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Explore Discussions' in body
    assert 'Browse Programmes' in body


def test_index_journey_query_param_overrides_accept_language(app, db):
    """Explicit ?journey= slug wins over browser language (VPN / wrong locale safe)."""
    from app.models import Programme, User

    with app.app_context():
        u = User(username="jroute", email="jroute@example.com", password="hashed-password")
        db.session.add(u)
        db.session.flush()
        de = Programme(
            slug="humanity-big-questions-de",
            name="DE Journey",
            creator_id=u.id,
            geographic_scope="country",
            country="Germany",
            themes=[],
            phases=[],
            cohorts=[],
        )
        nl = Programme(
            slug="humanity-big-questions-nl",
            name="NL Journey",
            creator_id=u.id,
            geographic_scope="country",
            country="Netherlands",
            themes=[],
            phases=[],
            cohorts=[],
        )
        db.session.add_all([de, nl])
        db.session.commit()

    client = app.test_client()
    resp = client.get(
        "/?journey=humanity-big-questions-nl",
        headers={"Accept-Language": "de-DE,de;q=0.9"},
    )
    body = resp.get_data(as_text=True)
    assert resp.status_code == 200
    assert "Your pick" in body
    assert "humanity-big-questions-nl" in body
    assert "Edition for Germany" not in body
