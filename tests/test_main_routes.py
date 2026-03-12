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
