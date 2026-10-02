"""Opinion groups are published only when the votes show them.

Clustering always returns groups. These tests hold the check that decides
whether a split means anything, and what each surface shows when it does not.
"""
import numpy as np
import pandas as pd
import pytest

from app.lib.consensus_engine import assess_group_structure
from app.models import ConsensusAnalysis, Discussion, Statement, StatementVote, User, generate_slug

pytestmark = pytest.mark.usefixtures('sqlite_vote_functions')


def _frame(matrix):
    return pd.DataFrame(matrix, index=[f'p{i}' for i in range(matrix.shape[0])], columns=list(range(1, matrix.shape[1] + 1)))


def _two_camps(rng, participants=30, statements=10):
    side = np.where(np.arange(participants) < participants // 2, 1.0, -1.0)
    votes = np.outer(side, rng.choice([1.0, -1.0], size=statements))
    votes[:, :3] = 1.0  # common ground both camps share
    noise = rng.random(votes.shape) < 0.1
    votes[noise] = rng.choice([1.0, 0.0, -1.0], size=noise.sum())
    return _frame(votes)


_SEEDS = range(6)


def _supported(make_votes) -> int:
    """How many of six independent audiences the test finds groups in."""
    return sum(
        assess_group_structure(make_votes(np.random.default_rng(100 + seed)), n_permutations=19, seed=seed)['supported']
        for seed in _SEEDS
    )


def test_two_real_camps_are_recognised():
    # Missing one clear split in six is tolerated: with 19 shuffles a single tie fails the test.
    assert _supported(lambda rng: _two_camps(rng, participants=30, statements=10)) >= len(_SEEDS) - 1


@pytest.mark.parametrize('weights', [
    (0.4, 0.2, 0.4),   # people answering at random
    (0.8, 0.1, 0.1),   # an audience that broadly agrees
])
def test_an_audience_with_no_camps_gets_no_groups(weights):
    # The test is allowed a false alarm about one time in twenty. Three in six
    # would be a sign it is broken.
    found = _supported(lambda rng: _frame(rng.choice([1.0, 0.0, -1.0], size=(24, 8), p=weights)))

    assert found <= 2


def test_uneven_participation_alone_is_not_mistaken_for_groups():
    def _votes(rng):
        votes = rng.choice([1.0, 0.0, -1.0], size=(24, 8), p=(0.5, 0.2, 0.3))
        light_voters = rng.random(24) < 0.4
        votes[np.ix_(light_voters, range(3, 8))] = np.nan
        return _frame(votes)

    assert _supported(_votes) <= 2


def test_the_test_keeps_each_statements_votes_and_each_persons_answers(monkeypatch):
    """The shuffled audiences must differ from the real one only in who gave which answer."""
    from app.lib import consensus_engine

    rng = np.random.default_rng(5)
    votes = rng.choice([1.0, 0.0, -1.0], size=(20, 6))
    votes[rng.random(votes.shape) < 0.3] = np.nan
    frame = _frame(votes)
    seen = []
    real_scaling = consensus_engine.apply_sparsity_scaling

    def _record(coordinates, matrix):
        seen.append(matrix.copy())
        return real_scaling(coordinates, matrix)

    monkeypatch.setattr(consensus_engine, 'apply_sparsity_scaling', _record)
    assess_group_structure(frame, n_permutations=3, seed=5)

    assert len(seen) == 4
    for shuffled in seen[1:]:
        assert (shuffled.notna().to_numpy() == frame.notna().to_numpy()).all()
        for column in frame.columns:
            assert sorted(shuffled[column].dropna()) == sorted(frame[column].dropna())


# ── What each surface shows ─────────────────────────────────────────────────

def _discussion_with_analysis(db, *, group_structure):
    user = User(username='owner', email='owner@example.org', password='x')
    db.session.add(user)
    db.session.flush()
    discussion = Discussion(
        title='Should the town centre be car-free?', slug=generate_slug('Should the town centre be car-free?'),
        creator_id=user.id, has_native_statements=True, topic='Society', geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()
    statement = Statement(discussion_id=discussion.id, user_id=user.id, content='Cars should be kept out of the centre.')
    db.session.add(statement)
    db.session.flush()
    for number in range(24):
        db.session.add(StatementVote(
            statement_id=statement.id, discussion_id=discussion.id,
            session_fingerprint=f'fp-{number}', vote=1 if number < 20 else -1,
        ))
    metadata = {'stability_mean_ari': 1.0, 'stability_runs': 3}
    if group_structure is not None:
        metadata['group_structure'] = group_structure
    analysis = ConsensusAnalysis(
        discussion_id=discussion.id, num_clusters=3, silhouette_score=0.8, method='agglomerative',
        participants_count=24, statements_count=1,
        cluster_data={
            'metadata': metadata, 'cluster_assignments': {}, 'pca_coordinates': {},
            'consensus_statements': [], 'bridge_statements': [], 'divisive_statements': [],
            'representative_statements': {},
        },
    )
    db.session.add(analysis)
    db.session.commit()
    return user, discussion, analysis


def _login(client, user):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user.id)
        sess['_fresh'] = True


def test_unsupported_groups_are_not_drawn_and_the_statement_results_are_shown(app, db, client):
    user, discussion, analysis = _discussion_with_analysis(db, group_structure={'supported': False, 'p_value': 0.4})
    _login(client, user)

    page = client.get(f'/discussions/{discussion.id}/consensus', follow_redirects=True)
    text = page.get_data(as_text=True)

    assert page.status_code == 200
    assert 'No distinct opinion groups' in text and 'Where participants agree' in text
    assert 'Cars should be kept out of the centre.' in text
    assert 'Opinion Groups' not in text and 'Analysis Not Ready' not in text
    assert analysis.published_group_count == 0

    data = client.get(f'/api/discussions/{discussion.id}/consensus/data').get_json()
    assert data['error'] == 'analysis_withheld' and 'do not show distinct opinion groups' in data['message']


def test_supported_and_older_analyses_keep_their_groups(app, db):
    _user, _discussion, supported = _discussion_with_analysis(db, group_structure={'supported': True, 'p_value': 0.025})
    assert supported.groups_supported and supported.published_group_count == 3

    older = ConsensusAnalysis(
        discussion_id=supported.discussion_id, num_clusters=2, cluster_data={'metadata': {}},
    )
    assert older.groups_supported and older.published_group_count == 2, 'no verdict recorded: not withdrawn'


def test_partners_are_told_there_are_no_groups(app, db):
    from app.partner.events import serialize_consensus_payload

    _user, discussion, analysis = _discussion_with_analysis(db, group_structure={'supported': False, 'p_value': 0.4})

    assert serialize_consensus_payload(discussion, analysis)['num_clusters'] == 0


def test_vote_direction_is_not_sent_to_analytics(app):
    from app.lib.posthog_utils import safe_posthog_capture

    sent = []

    class _Client:
        project_api_key = 'phc_test'

        def capture(self, **kwargs):
            sent.append(kwargs)

    properties = {'statement_id': 4, 'vote': 'agree', 'vote_choice': 'agree', 'source': 'web'}
    browser = {'User-Agent': 'Mozilla/5.0 (Macintosh) AppleWebKit/605.1.15 Version/17.0 Safari/605.1.15'}
    with app.test_request_context('/', headers=browser):
        assert safe_posthog_capture(posthog_client=_Client(), distinct_id='42', event='statement_voted', properties=properties)
        app.config['ANALYTICS_INCLUDE_VOTE_DIRECTION'] = True
        try:
            safe_posthog_capture(posthog_client=_Client(), distinct_id='42', event='statement_voted', properties=properties)
        finally:
            app.config['ANALYTICS_INCLUDE_VOTE_DIRECTION'] = False

    assert sent[0]['properties']['statement_id'] == 4
    assert 'vote' not in sent[0]['properties'] and 'vote_choice' not in sent[0]['properties']
    assert sent[1]['properties']['vote'] == 'agree', 'a deployment can opt back in'
