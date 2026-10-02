"""The slugged ``consensus_url`` given to partners must reach the results page."""
from app.api.utils import build_discussion_urls
from tests.test_consensus_report_and_export import _create_user, _discussion


def test_partner_consensus_url_redirects_to_results_page(app, db, client):
    owner = _create_user(db, 'slugowner', 'slugowner@example.com')
    discussion = _discussion(db, owner.id)
    db.session.commit()

    with app.test_request_context():
        consensus_url = build_discussion_urls(discussion, include_ref=False)['consensus_url']
    path = consensus_url.replace(app.config.get('BASE_URL', 'https://societyspeaks.io'), '')

    response = client.get(f'{path}?ref=observer')

    assert response.status_code == 301
    assert response.headers['Location'].endswith(
        f'/discussions/{discussion.id}/consensus?ref=observer'
    )
