"""Published consensus data must not identify participants.

``ConsensusAnalysis.cluster_data`` stores each participant's opinion group and
chart position keyed by ``u_<user id>`` or ``a_<cookie fingerprint>``. Those
keys stay on the server: public endpoints return aggregates and anonymous
points only. AI summaries and labels are an owner action.
"""
import json

from app.models import ConsensusAnalysis, UserAPIKey
from tests.test_consensus_report_and_export import (
    _create_user,
    _login,
    _seed_report_fixture,
)


def _seed(app, db):
    with app.app_context():
        owner, discussion, ids = _seed_report_fixture(db)
        return owner.id, discussion.id, ids


def _assert_no_participant_ids(body: str):
    assert 'cluster_assignments' not in body
    assert 'pca_coordinates' not in body
    for i in range(12):
        assert f'"u_{i}"' not in body


def test_cluster_data_returns_anonymous_points(app, db, client):
    _owner_id, discussion_id, _ids = _seed(app, db)

    resp = client.get(f'/api/discussions/{discussion_id}/consensus/data')

    assert resp.status_code == 200
    _assert_no_participant_ids(resp.get_data(as_text=True))
    data = resp.get_json()
    assert set(data) == {'points', 'metadata'}
    assert len(data['points']) == 12
    assert sorted(p['cluster'] for p in data['points']) == [0] * 6 + [1] * 6
    assert all(set(p) == {'x', 'y', 'cluster'} for p in data['points'])
    # Ordered by position, not by the stored participant order.
    assert data['points'] == sorted(
        data['points'], key=lambda p: (str(p['cluster']), p['x'], p['y'])
    )


def test_cluster_data_marks_only_the_viewers_own_point(app, db, client):
    owner_id, discussion_id, _ids = _seed(app, db)
    _login(client, owner_id)

    resp = client.get(f'/api/discussions/{discussion_id}/consensus/data')

    viewer_points = [p for p in resp.get_json()['points'] if p.get('is_viewer')]
    assert len(viewer_points) == 1
    # The fixture stores ``u_<i>`` at (0.1 * i, -0.1 * i).
    assert viewer_points[0]['x'] == round(0.1 * owner_id, 4)
    assert 'private' in resp.headers['Cache-Control']
    assert 'no-store' in resp.headers['Cache-Control']


def test_json_export_carries_aggregates_only(app, db, client):
    _owner_id, discussion_id, ids = _seed(app, db)
    with app.app_context():
        analysis = ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).one()
        analysis.cluster_data['summary_generated_by'] = 99
        analysis.cluster_data['a_future_engine_key'] = {'u_1': 'private'}
        db.session.commit()

    resp = client.get(f'/api/discussions/{discussion_id}/consensus/export')

    assert resp.status_code == 200
    _assert_no_participant_ids(resp.get_data(as_text=True))
    data = resp.get_json()['data']
    assert 'summary_generated_by' not in data
    assert 'a_future_engine_key' not in data, 'export must be an allowlist'
    assert data['cluster_sizes'] == {'0': 6, '1': 6}
    assert data['metadata']
    exported_ids = {entry['statement_id'] for entry in data['consensus_statements']}
    assert ids['agreed'] in exported_ids
    assert ids['hidden'] not in exported_ids, 'moderated statements must not be exported'


def test_statements_endpoint_omits_moderated_statements(app, db, client):
    _owner_id, discussion_id, ids = _seed(app, db)

    resp = client.get(f'/api/discussions/{discussion_id}/consensus/statements')

    data = resp.get_json()
    listed = {entry['statement_id'] for entry in data['consensus']}
    assert ids['agreed'] in listed
    assert ids['hidden'] not in listed
    assert [entry['statement_id'] for entry in data['divisive']] == [ids['split']]


def test_results_page_does_not_embed_participant_keys(app, db, client):
    owner_id, discussion_id, _ids = _seed(app, db)
    _login(client, owner_id)

    body = client.get(f'/discussions/{discussion_id}/consensus').get_data(as_text=True)

    assert 'viewerKeys' not in body
    assert f'u_{owner_id}' not in body
    assert 'The larger ringed dot is you.' in body


def test_results_page_does_not_promise_a_dot_to_a_viewer_who_is_not_plotted(app, db, client):
    _owner_id, discussion_id, _ids = _seed(app, db)
    with app.app_context():
        outsider = _create_user(db, 'unplotted', 'unplotted@example.com')
        outsider.is_admin = True  # admins bypass the participation gate
        outsider_id = outsider.id
        analysis = ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).one()
        assignments = dict(analysis.cluster_data['cluster_assignments'])
        assignments.pop(f'u_{outsider_id}', None)
        analysis.cluster_data['cluster_assignments'] = assignments
        db.session.commit()
    _login(client, outsider_id)

    body = client.get(f'/discussions/{discussion_id}/consensus').get_data(as_text=True)

    assert 'The larger ringed dot is you.' not in body


def test_summary_api_does_not_name_who_generated_it(app, db, client):
    _owner_id, discussion_id, _ids = _seed(app, db)
    with app.app_context():
        analysis = ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).one()
        analysis.cluster_data['ai_summary'] = 'People broadly agree.'
        analysis.cluster_data['summary_generated_by'] = 99
        db.session.commit()

    data = client.get(f'/api/discussions/{discussion_id}/consensus/summary').get_json()

    assert data['summary'] == 'People broadly agree.'
    assert 'generated_by' not in data


def _other_user_with_key(app, db):
    with app.app_context():
        other = _create_user(db, 'bystander', 'bystander@example.com')
        db.session.add(UserAPIKey(
            user_id=other.id, provider='anthropic',
            encrypted_api_key='x', is_active=True,
        ))
        db.session.commit()
        return other.id


def test_only_the_owner_can_generate_a_summary(app, db, client, monkeypatch):
    _owner_id, discussion_id, _ids = _seed(app, db)
    called = []
    monkeypatch.setattr(
        'app.lib.llm_utils.generate_discussion_summary',
        lambda **kwargs: called.append(kwargs) or 'summary',
    )
    _login(client, _other_user_with_key(app, db))

    resp = client.post(f'/discussions/{discussion_id}/consensus/generate-summary')

    assert resp.status_code == 403
    assert called == []


def test_only_the_owner_can_generate_labels(app, db, client, monkeypatch):
    _owner_id, discussion_id, _ids = _seed(app, db)
    called = []
    monkeypatch.setattr(
        'app.lib.llm_utils.generate_cluster_labels',
        lambda **kwargs: called.append(kwargs) or {},
    )
    _login(client, _other_user_with_key(app, db))

    resp = client.post(f'/discussions/{discussion_id}/consensus/generate-labels')

    assert resp.status_code == 403
    assert called == []


def test_summary_sends_only_published_statements_and_leaves_the_analysis_untouched(
    app, db, client, monkeypatch
):
    owner_id, discussion_id, ids = _seed(app, db)
    with app.app_context():
        db.session.add(UserAPIKey(
            user_id=owner_id, provider='anthropic',
            encrypted_api_key='x', is_active=True,
        ))
        db.session.commit()
    sent = {}

    def _fake_summary(**kwargs):
        sent.update(kwargs)
        return 'People broadly agree.'

    monkeypatch.setattr('app.lib.llm_utils.generate_discussion_summary', _fake_summary)
    _login(client, owner_id)

    resp = client.post(f'/discussions/{discussion_id}/consensus/generate-summary')

    assert resp.status_code == 302
    sent_text = json.dumps(sent['consensus_statements'])
    assert 'Everyone broadly agrees with this one.' in sent_text
    assert 'rejected by moderation' not in sent_text
    with app.app_context():
        analysis = ConsensusAnalysis.query.filter_by(discussion_id=discussion_id).one()
        assert analysis.cluster_data['ai_summary'] == 'People broadly agree.'
        stored = analysis.cluster_data['consensus_statements']
        assert all('content' not in entry for entry in stored), (
            'statement text must not be written into the stored analysis'
        )


def test_labels_send_only_published_statements(app, db, client, monkeypatch):
    owner_id, discussion_id, _ids = _seed(app, db)
    with app.app_context():
        db.session.add(UserAPIKey(
            user_id=owner_id, provider='anthropic',
            encrypted_api_key='x', is_active=True,
        ))
        db.session.commit()
    sent = {}

    def _fake_labels(**kwargs):
        sent.update(kwargs)
        return {}

    monkeypatch.setattr('app.lib.llm_utils.generate_cluster_labels', _fake_labels)
    _login(client, owner_id)

    client.post(f'/discussions/{discussion_id}/consensus/generate-labels')

    contents = [s['content'] for s in sent['statements']]
    assert 'Everyone broadly agrees with this one.' in contents
    assert not any('rejected by moderation' in c for c in contents)
