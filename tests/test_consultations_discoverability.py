"""The paid consultation product is reachable from the pages people read first."""
import pytest


@pytest.fixture
def selling(app):
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = True
    yield app


@pytest.mark.parametrize('path, marks', [
    ('/', ['home-consult-heading', 'home-consultations-start', '/consultations/start']),
    ('/about', ['about-consult-heading', 'about-hero-consultations', '/consultations/self-serve']),
    ('/help/', ['help-hub-consultations', '/help/consultations']),
    ('/help/getting-started', ['getting-started-consultations', '/consultations/self-serve']),
])
def test_pages_lead_to_the_consultation_product(client, db, selling, path, marks):
    html = client.get(path).get_data(as_text=True)
    for mark in marks:
        assert mark in html, f'{path} lacks {mark}'


def test_consultations_lead_the_build_section_of_the_help_hub(client, db, selling):
    html = client.get('/help/').get_data(as_text=True)
    build = html.index('help-section-build')
    assert html.index('/help/consultations', build) < html.index('/help/civic-infrastructure', build)


def test_pages_keep_their_old_routes_while_the_product_is_off(client, db, app):
    app.config['CONSULTATIONS_SELF_SERVE_ENABLED'] = False
    assert 'home-consult-heading' not in client.get('/').get_data(as_text=True)
    about = client.get('/about').get_data(as_text=True)
    assert 'about-consult-heading' not in about and '/help/civic-infrastructure' in about
