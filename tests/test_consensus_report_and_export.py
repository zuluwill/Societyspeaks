"""
Consensus report + CSV export regressions.

These cover three product-visible defects:

1. The report template read ``bridge_score`` / ``division_score`` — fields the
   engine has never produced — so every row printed "0.00".
2. The CSV export read ``Statement.agree_count`` / ``disagree_count``, which
   do not exist (the model stores ``vote_count_*``), so every row exported
   zero votes.
3. The "newer votes are in" banner compared a sum of votes with a participant
   count, and all live statements with the analysis's *voted* statements, so
   it fired on almost every analysis.
"""
import csv
import io

from app.discussions.consensus import detect_analysis_drift
from app.models import (
    ConsensusAnalysis,
    Discussion,
    DiscussionTranslation,
    Statement,
    StatementTranslation,
    StatementVote,
    User,
    generate_slug,
)


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _discussion(db, creator_id, title='Consensus Report Fixture'):
    d = Discussion(
        title=title,
        slug=generate_slug(title),
        creator_id=creator_id,
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(d)
    db.session.flush()
    return d


def _statement(db, discussion_id, user_id, content, agree=0, disagree=0, unsure=0):
    stmt = Statement(
        discussion_id=discussion_id,
        user_id=user_id,
        content=content,
        vote_count_agree=agree,
        vote_count_disagree=disagree,
        vote_count_unsure=unsure,
    )
    db.session.add(stmt)
    db.session.flush()
    return stmt


def _analysis(db, discussion_id, cluster_data, participants=12, statements=3):
    analysis = ConsensusAnalysis(
        discussion_id=discussion_id,
        cluster_data=cluster_data,
        num_clusters=2,
        silhouette_score=0.42,
        method='pca_kmeans',
        participants_count=participants,
        statements_count=statements,
    )
    db.session.add(analysis)
    db.session.flush()
    return analysis


def _publishable_metadata():
    """Metadata that satisfies ``_assess_analysis_publishability``."""
    return {
        'stability_runs': 5,
        'stability_mean_ari': 0.80,
        'stability_consensus_jaccard_mean': 0.75,
    }


def _cluster_data(consensus_id=1, bridge_id=2, divisive_id=3):
    return {
        'cluster_assignments': {f'u_{i}': (0 if i < 6 else 1) for i in range(12)},
        'pca_coordinates': {f'u_{i}': (0.1 * i, -0.1 * i) for i in range(12)},
        'consensus_statements': [{
            'statement_id': consensus_id,
            'agreement_rate': 0.90,
            'wilson_low': 0.74,
            'wilson_high': 0.97,
            'agree_count': 18,
            'disagree_count': 2,
            'vote_count': 20,
            'cluster_agreements': [0.9, 0.9],
        }],
        'bridge_statements': [{
            'statement_id': bridge_id,
            'mean_agreement': 0.08,
            'mean_disagreement': 0.88,
            'min_cluster_agreement': 0.05,
            'min_cluster_disagreement': 0.82,
            'group_gap': 0.06,
            'variance': 0.001,
            'polarity': 'reject',
            'cluster_agreements': [0.05, 0.11],
            'cluster_disagreements': [0.82, 0.94],
            'agree_count': 2,
            'disagree_count': 18,
            'disagree_strict_count': 17,
            'vote_count': 20,
            'wilson_low': 0.67,
            'wilson_high': 0.95,
        }],
        'divisive_statements': [{
            'statement_id': divisive_id,
            'agree_rate': 0.5,
            'controversy_score': 1.0,
            'variance': 0.25,
            'group_gap': 0.84,
            'gap_ci_low': 0.52,
            'gap_ci_high': 0.96,
            'wilson_low': 0.52,
            'wilson_high': 0.96,
            'max_agreement': 0.92,
            'min_agreement': 0.08,
            'max_cluster_id': 0,
            'min_cluster_id': 1,
            'cluster_agreements': [0.92, 0.08],
            'p_value': 0.001,
            'p_value_gap': 0.002,
            'chi2': 14.2,
            'significant': True,
            'fdr_method': 'bh',
        }],
        'representative_statements': {},
        'pca_axis_loadings': {},
        'metadata': _publishable_metadata(),
    }


def _seed_report_fixture(db):
    owner = _create_user(db, 'reportowner', 'reportowner@example.com')
    discussion = _discussion(db, owner.id)
    # Insert the weakest consensus statement first so primary-key order
    # disagrees with the engine's ranking (safest signal first).
    weak = _statement(db, discussion.id, owner.id, 'A weaker agreement that must not lead the list.', agree=12, disagree=8)
    agreed = _statement(db, discussion.id, owner.id, 'Everyone broadly agrees with this one.', agree=18, disagree=2)
    rejected = _statement(db, discussion.id, owner.id, 'Every group rejects this proposal outright.', agree=2, disagree=17, unsure=1)
    split = _statement(db, discussion.id, owner.id, 'This one splits the groups right down the middle.', agree=10, disagree=10)
    hidden = _statement(db, discussion.id, owner.id, 'This statement was rejected by moderation and must not be published.', agree=20)
    hidden.mod_status = -1
    data = _cluster_data(agreed.id, rejected.id, split.id)
    data['consensus_statements'].append({
        'statement_id': weak.id,
        'agreement_rate': 0.60,
        'wilson_low': 0.40,
        'wilson_high': 0.78,
        'vote_count': 20,
    })
    data['consensus_statements'].append({
        'statement_id': hidden.id,
        'agreement_rate': 0.99,
        'wilson_low': 0.90,
        'wilson_high': 1.0,
        'vote_count': 20,
    })
    # Engine order is the list order: strongest first, then the weaker one.
    _analysis(db, discussion.id, data)
    db.session.commit()
    return owner, discussion, {
        'agreed': agreed.id,
        'rejected': rejected.id,
        'split': split.id,
        'weak': weak.id,
        'hidden': hidden.id,
    }


def test_report_renders_real_engine_metrics_not_zero_scores(app, db, client):
    with app.app_context():
        owner, discussion, ids = _seed_report_fixture(db)
        discussion_id = discussion.id
        owner_id = owner.id

    _login(client, owner_id)
    resp = client.get(f'/discussions/{discussion_id}/consensus/report')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)

    # The fields the old template read never existed in engine output.
    assert 'Bridge score' not in body
    assert 'Division score' not in body
    assert '0.00' not in body.split('Bridge Statements')[-1].split('Points of Division')[0]

    # Bridge: polarity-aware, reporting the per-group floor the gate tested.
    assert 'Shared rejection' in body
    assert '82%' in body          # min_cluster_disagreement
    # Divisive: the real group gap and its CI.
    assert '84%' in body          # group_gap
    assert 'FDR-significant' in body
    # Consensus: agreement rate and Wilson interval.
    assert '90% agreement' in body
    # Engine list order, not primary-key order. The weaker statement was
    # inserted first and must not lead the section.
    agreed_at = body.find('Everyone broadly agrees')
    weaker_at = body.find('A weaker agreement')
    assert agreed_at != -1 and weaker_at != -1 and agreed_at < weaker_at
    assert 'rejected by moderation' not in body

    results = client.get(f'/discussions/{discussion_id}/consensus')
    assert results.status_code == 200
    results_body = results.get_data(as_text=True)
    assert results_body.find('Everyone broadly agrees') < results_body.find('A weaker agreement')
    assert 'rejected by moderation' not in results_body


def test_csv_export_reports_real_vote_counts(app, db, client):
    with app.app_context():
        owner, discussion, ids = _seed_report_fixture(db)
        discussion_id = discussion.id
        owner_id = owner.id

    _login(client, owner_id)
    resp = client.get(
        f'/api/discussions/{discussion_id}/consensus/export?format=csv'
    )
    assert resp.status_code == 200

    text = resp.get_data(as_text=True).lstrip('﻿')
    rows = list(csv.DictReader(io.StringIO(text)))
    by_id = {int(r['statement_id']): r for r in rows}
    assert ids['hidden'] not in by_id
    assert ids['weak'] in by_id

    consensus_row = by_id[ids['agreed']]
    assert int(consensus_row['agree_count']) == 18
    assert int(consensus_row['disagree_count']) == 2
    assert int(consensus_row['total_votes']) == 20
    assert consensus_row['classification'] == 'consensus'

    bridge_row = by_id[ids['rejected']]
    assert int(bridge_row['agree_count']) == 2
    assert int(bridge_row['disagree_count']) == 17
    assert int(bridge_row['unsure_count']) == 1
    assert int(bridge_row['total_votes']) == 20
    assert bridge_row['polarity'] == 'reject'

    # Every row must carry a non-zero vote total — the old export read
    # attribute names the model does not define and wrote 0 everywhere.
    assert all(int(r['total_votes']) > 0 for r in rows)


def test_csv_export_neutralises_formula_injection(app, db, client):
    """The file carries a UTF-8 BOM so Excel opens it. A leading '=' would run."""
    with app.app_context():
        owner = _create_user(db, 'formulas', 'formulas@example.com')
        discussion = _discussion(db, owner.id, title='Formula Export')
        stmt = _statement(
            db, discussion.id, owner.id,
            '=HYPERLINK("http://evil.example") click',
            agree=10, disagree=1,
        )
        _analysis(db, discussion.id, {
            'cluster_assignments': {},
            'consensus_statements': [{
                'statement_id': stmt.id,
                'agreement_rate': 0.9,
                'vote_count': 11,
            }],
            'bridge_statements': [],
            'divisive_statements': [],
            'representative_statements': {},
            'metadata': _publishable_metadata(),
        }, statements=1)
        db.session.commit()
        discussion_id, owner_id = discussion.id, owner.id

    _login(client, owner_id)
    resp = client.get(f'/api/discussions/{discussion_id}/consensus/export?format=csv')
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True).lstrip('﻿'))))
    assert rows[0]['content'].startswith("'=")
    assert not rows[0]['content'].startswith('=')


def test_csv_export_keeps_a_zero_agreement_rate(app, db, client):
    """``entry.get(a) or entry.get(b)`` discarded a legitimate 0.0 rate —
    exactly what a unanimously-rejected statement scores."""
    with app.app_context():
        owner = _create_user(db, 'zerorate', 'zerorate@example.com')
        discussion = _discussion(db, owner.id, title='Zero Rate Export')
        stmt = _statement(
            db, discussion.id, owner.id,
            'Nobody at all agrees with this statement.',
            agree=0, disagree=20,
        )
        _analysis(db, discussion.id, {
            'cluster_assignments': {},
            'consensus_statements': [],
            'bridge_statements': [{
                'statement_id': stmt.id,
                'mean_agreement': 0.0,
                'mean_disagreement': 1.0,
                'min_cluster_agreement': 0.0,
                'min_cluster_disagreement': 1.0,
                'group_gap': 0.0,
                'polarity': 'reject',
                'vote_count': 20,
            }],
            'divisive_statements': [],
            'representative_statements': {},
            'metadata': _publishable_metadata(),
        }, statements=1)
        db.session.commit()
        discussion_id, owner_id = discussion.id, owner.id

    _login(client, owner_id)
    resp = client.get(
        f'/api/discussions/{discussion_id}/consensus/export?format=csv'
    )
    assert resp.status_code == 200
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True).lstrip('﻿'))))
    assert rows[0]['agreement_rate'] == '0.0'


def test_csv_export_keeps_every_classification_for_one_statement(app, db, client):
    """A statement that is both consensus and bridge must not lose a label."""
    with app.app_context():
        owner = _create_user(db, 'multiclass', 'multiclass@example.com')
        discussion = _discussion(db, owner.id, title='Multi Class Export')
        stmt = _statement(
            db, discussion.id, owner.id,
            'A statement every single group agrees with.',
            agree=19, disagree=1,
        )
        _analysis(db, discussion.id, {
            'cluster_assignments': {},
            'consensus_statements': [{
                'statement_id': stmt.id,
                'agreement_rate': 0.95,
                'wilson_low': 0.80,
                'wilson_high': 0.99,
                'vote_count': 20,
            }],
            'bridge_statements': [{
                'statement_id': stmt.id,
                'mean_agreement': 0.95,
                'min_cluster_agreement': 0.9,
                'group_gap': 0.05,
                'polarity': 'agree',
                'vote_count': 20,
            }],
            'divisive_statements': [],
            'representative_statements': {},
            'metadata': _publishable_metadata(),
        }, statements=1)
        db.session.commit()
        discussion_id, owner_id = discussion.id, owner.id

    _login(client, owner_id)
    resp = client.get(
        f'/api/discussions/{discussion_id}/consensus/export?format=csv'
    )
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True).lstrip('﻿'))))
    assert rows[0]['classification'] == 'consensus;bridge'
    assert rows[0]['polarity'] == 'agree'


# ── Stale-analysis detection ─────────────────────────────────────────────

def _vote(db, discussion_id, statement_id, *, user_id=None, fingerprint=None, vote=1):
    db.session.add(StatementVote(
        statement_id=statement_id,
        discussion_id=discussion_id,
        user_id=user_id,
        session_fingerprint=fingerprint,
        vote=vote,
    ))


def test_drift_ignores_statements_nobody_has_voted_on(app, db):
    """``analysis.statements_count`` is the vote-matrix column count, so an
    unvoted statement is not drift — it was never clusterable."""
    with app.app_context():
        owner = _create_user(db, 'driftowner', 'driftowner@example.com')
        discussion = _discussion(db, owner.id, title='Drift Unvoted')
        voted = _statement(db, discussion.id, owner.id, 'A statement people voted on.', agree=1)
        _statement(db, discussion.id, owner.id, 'A statement nobody has voted on yet.')
        _vote(db, discussion.id, voted.id, user_id=owner.id)
        analysis = _analysis(db, discussion.id, {'metadata': {}}, participants=1, statements=1)
        db.session.commit()

        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_stmt_count'] == 1
        assert drift['has_new_statements'] is False
        assert drift['is_stale'] is False


def test_drift_does_not_fire_when_participants_merely_voted_a_lot(app, db):
    """The old test compared total votes with the participant count, so two
    votes per participant was enough to claim the analysis was stale."""
    with app.app_context():
        owner = _create_user(db, 'busyvoter', 'busyvoter@example.com')
        discussion = _discussion(db, owner.id, title='Drift Many Votes')
        statements = [
            _statement(db, discussion.id, owner.id, f'Statement number {i} for drift testing.', agree=2)
            for i in range(5)
        ]
        voters = [_create_user(db, f'drifter{i}', f'drifter{i}@example.com') for i in range(2)]
        for stmt in statements:
            for voter in voters:
                _vote(db, discussion.id, stmt.id, user_id=voter.id)
        analysis = _analysis(db, discussion.id, {'metadata': {}}, participants=2, statements=5)
        db.session.commit()

        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_participant_count'] == 2
        assert drift['has_new_participants'] is False
        assert drift['is_stale'] is False, (
            '10 votes from the 2 analysed participants is not new participation'
        )


def test_drift_fires_on_genuinely_new_participants(app, db):
    with app.app_context():
        owner = _create_user(db, 'newpartowner', 'newpartowner@example.com')
        discussion = _discussion(db, owner.id, title='Drift New Participants')
        stmt = _statement(db, discussion.id, owner.id, 'A statement for new participant drift.', agree=6)
        for i in range(6):
            _vote(db, discussion.id, stmt.id, fingerprint=f'anon-drift-fingerprint-{i}')
        analysis = _analysis(db, discussion.id, {'metadata': {}}, participants=3, statements=1)
        db.session.commit()

        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_participant_count'] == 6
        assert drift['has_new_participants'] is True
        assert drift['is_stale'] is True


def test_drift_ignores_denormalised_counters_with_no_vote_rows(app, db):
    """``vote_count_*`` can run ahead of the rows the engine clustered."""
    with app.app_context():
        owner = _create_user(db, 'counterdrift', 'counterdrift@example.com')
        discussion = _discussion(db, owner.id, title='Counter Drift')
        _statement(
            db, discussion.id, owner.id,
            'Counters say this was voted on, but no vote row exists.',
            agree=8,
        )
        analysis = _analysis(db, discussion.id, {'metadata': {}}, participants=1, statements=0)
        db.session.commit()

        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_stmt_count'] == 0
        assert drift['has_new_statements'] is False
        assert drift['is_stale'] is False


def test_drift_oversize_compares_the_statement_catalog(app, db):
    """Oversize analyses store every non-deleted statement, voted or not."""
    with app.app_context():
        owner = _create_user(db, 'oversize', 'oversize@example.com')
        discussion = _discussion(db, owner.id, title='Oversize Drift')
        voted = _statement(db, discussion.id, owner.id, 'A statement people voted on already.', agree=1)
        _statement(db, discussion.id, owner.id, 'An unvoted statement that was in the catalog.')
        _vote(db, discussion.id, voted.id, user_id=owner.id)
        analysis = _analysis(
            db, discussion.id,
            {'metadata': {'oversize_mode': True}},
            participants=1,
            statements=2,
        )
        db.session.commit()

        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_stmt_count'] == 2
        assert drift['is_stale'] is False

        _statement(db, discussion.id, owner.id, 'A statement added after the analysis.')
        db.session.commit()
        drift = detect_analysis_drift(discussion, analysis)
        assert drift['current_stmt_count'] == 3
        assert drift['has_new_statements'] is True
        assert drift['is_stale'] is True


# ── Published visibility: soft-deleted statements and PCA axis labels ────

def test_deleted_statements_are_dropped_from_every_published_surface(app, db, client):
    """A statement deleted after the analysis ran must disappear from the
    results page, the report and the CSV — including the PCA axis labels,
    which were seeded from an unfiltered representative-statement fetch."""
    with app.app_context():
        owner = _create_user(db, 'deletedsurfaces', 'deletedsurfaces@example.com')
        discussion = _discussion(db, owner.id, title='Deleted Surfaces')
        kept = _statement(db, discussion.id, owner.id, 'A kept statement that should stay published.', agree=18, disagree=2)
        gone = _statement(db, discussion.id, owner.id, 'A deleted statement that must vanish everywhere.', agree=19, disagree=1)
        gone.is_deleted = True
        _analysis(db, discussion.id, {
            'cluster_assignments': {'u_1': 0, 'u_2': 1},
            'consensus_statements': [
                {'statement_id': kept.id, 'agreement_rate': 0.9, 'wilson_low': 0.74,
                 'wilson_high': 0.97, 'vote_count': 20},
                {'statement_id': gone.id, 'agreement_rate': 0.95, 'wilson_low': 0.80,
                 'wilson_high': 0.99, 'vote_count': 20},
            ],
            'bridge_statements': [],
            'divisive_statements': [],
            # The deleted statement is also a representative statement and a
            # PCA axis loading — both paths that used to leak it.
            'representative_statements': {
                '0': [{'statement_id': gone.id, 'agreement_rate': 0.95,
                       'vote_count': 20, 'agree_count': 19, 'direction': 'agree'}],
            },
            'pca_axis_loadings': {
                'pc1': {'positive_statement_ids': [gone.id],
                        'negative_statement_ids': [kept.id]},
            },
            'metadata': _publishable_metadata(),
        }, statements=2)
        db.session.commit()
        discussion_id, owner_id = discussion.id, owner.id

    _login(client, owner_id)
    needle = 'must vanish everywhere'

    results = client.get(f'/discussions/{discussion_id}/consensus')
    assert results.status_code == 200
    assert needle not in results.get_data(as_text=True)

    report = client.get(f'/discussions/{discussion_id}/consensus/report')
    assert report.status_code == 200
    assert needle not in report.get_data(as_text=True)

    export = client.get(f'/api/discussions/{discussion_id}/consensus/export?format=csv')
    assert export.status_code == 200
    csv_text = export.get_data(as_text=True)
    assert needle not in csv_text
    assert 'should stay published' in csv_text


def test_csv_export_omits_statements_whose_row_is_gone(app, db, client):
    """A purged statement id must not export a row of blanks."""
    with app.app_context():
        owner = _create_user(db, 'purged', 'purged@example.com')
        discussion = _discussion(db, owner.id, title='Purged Export')
        kept = _statement(db, discussion.id, owner.id, 'The only statement still in the table.', agree=10, disagree=1)
        _analysis(db, discussion.id, {
            'cluster_assignments': {},
            'consensus_statements': [
                {'statement_id': kept.id, 'agreement_rate': 0.9, 'vote_count': 11},
                # An id with no row at all (hard-deleted / GDPR purge).
                {'statement_id': 9_999_999, 'agreement_rate': 0.8, 'vote_count': 10},
            ],
            'bridge_statements': [],
            'divisive_statements': [],
            'representative_statements': {},
            'metadata': _publishable_metadata(),
        }, statements=1)
        db.session.commit()
        discussion_id, owner_id, kept_id = discussion.id, owner.id, kept.id

    _login(client, owner_id)
    resp = client.get(f'/api/discussions/{discussion_id}/consensus/export?format=csv')
    rows = list(csv.DictReader(io.StringIO(resp.get_data(as_text=True).lstrip('﻿'))))
    assert [int(r['statement_id']) for r in rows] == [kept_id]


# ── Legacy analyses: stored before polarity / per-group floors existed ───

def test_legacy_bridge_entry_without_polarity_is_not_labelled_agreement(app, db, client):
    """Entries saved before `polarity` existed must infer it from the rates,
    not default to 'Shared agreement' and show a low agreement figure."""
    with app.app_context():
        owner = _create_user(db, 'legacybridge', 'legacybridge@example.com')
        discussion = _discussion(db, owner.id, title='Legacy Bridge')
        stmt = _statement(db, discussion.id, owner.id, 'An old shared rejection with no stored polarity.', agree=2, disagree=18)
        _analysis(db, discussion.id, {
            'cluster_assignments': {},
            'consensus_statements': [],
            'bridge_statements': [{
                # No polarity, no min_cluster_* — the old engine's shape.
                'statement_id': stmt.id,
                'mean_agreement': 0.10,
                'mean_disagreement': 0.90,
                'variance': 0.01,
                'vote_count': 20,
            }],
            'divisive_statements': [],
            'representative_statements': {},
            'metadata': _publishable_metadata(),
        }, statements=1)
        db.session.commit()
        discussion_id, owner_id = discussion.id, owner.id

    _login(client, owner_id)
    for path in (
        f'/discussions/{discussion_id}/consensus',
        f'/discussions/{discussion_id}/consensus/report',
    ):
        body = client.get(path).get_data(as_text=True)
        section = body[body.find('Bridge Statements'):]
        section = section[:section.find('Points of Division') if 'Points of Division' in section else len(section)]
        assert 'Shared rejection' in section, path
        assert 'Shared agreement' not in section, path
        # Falls back to the mean for the claimed polarity — 90%, not 10%.
        assert 'Mean cross-group: 90%' in section, path


def test_drift_statement_count_matches_the_engine_matrix_width(app, db):
    """The guarantee that matters: the live figure is literally the width of
    the matrix ``build_vote_matrix`` would produce right now. Asserting that
    against the engine — rather than restating its filters — is what stops the
    two definitions drifting apart again.
    """
    from app.discussions.consensus import _live_voted_statement_count
    from app.lib.consensus_engine import build_vote_matrix

    with app.app_context():
        owner = _create_user(db, 'matrixwidth', 'matrixwidth@example.com')
        discussion = _discussion(db, owner.id, title='Matrix Width')
        voters = [
            _create_user(db, f'widthvoter{i}', f'widthvoter{i}@example.com')
            for i in range(3)
        ]

        voted = [
            _statement(db, discussion.id, owner.id, f'A voted statement number {i} here.', agree=3)
            for i in range(4)
        ]
        # Never voted on → never a matrix column.
        _statement(db, discussion.id, owner.id, 'A statement with no votes at all.')
        # Deleted → excluded by the engine's own filter.
        deleted = _statement(db, discussion.id, owner.id, 'A deleted but voted statement.', agree=3)
        deleted.is_deleted = True
        # Counters inflated with no backing rows → must not count.
        _statement(db, discussion.id, owner.id, 'Counters say voted but no rows exist.', agree=99)

        for stmt in voted + [deleted]:
            for voter in voters:
                _vote(db, discussion.id, stmt.id, user_id=voter.id)
        # A vote row with neither identifier — build_vote_matrix skips it.
        orphan = _statement(db, discussion.id, owner.id, 'Only an unidentified vote row here.', agree=1)
        db.session.add(StatementVote(
            statement_id=orphan.id,
            discussion_id=discussion.id,
            user_id=None,
            session_fingerprint=None,
            vote=1,
        ))
        db.session.commit()

        _, _, _, statement_ids = build_vote_matrix(discussion.id, db)
        assert _live_voted_statement_count(discussion.id) == len(statement_ids) == 4


def _seed_translated_report(db):
    """One agreed statement with a French cache row, plus an untranslated one.

    Axis loadings store the agreed statement's id as a string, which is how a
    JSON round-trip can surface it.
    """
    french = 'Tout le monde est largement daccord avec ceci.'
    owner, discussion, ids = _seed_report_fixture(db)
    db.session.add(StatementTranslation(
        statement_id=ids['agreed'],
        language_code='fr',
        content=french,
    ))
    db.session.add(DiscussionTranslation(
        discussion_id=discussion.id,
        language_code='fr',
        title='Titre traduit du debat',
    ))
    analysis = ConsensusAnalysis.query.filter_by(discussion_id=discussion.id).one()
    data = dict(analysis.cluster_data)
    data['pca_axis_loadings'] = {
        'pc1': {
            'positive_statement_ids': [str(ids['agreed'])],
            'negative_statement_ids': [],
        },
    }
    analysis.cluster_data = data
    db.session.commit()
    return discussion.id, owner.id, french


def test_english_report_keeps_canonical_statement_text(app, db, client):
    """English is its own test: Flask-Babel pins the first request's locale
    for every later request in the same test function."""
    with app.app_context():
        discussion_id, owner_id, french = _seed_translated_report(db)

    _login(client, owner_id)
    english = client.get(f'/discussions/{discussion_id}/consensus/report')
    assert english.status_code == 200
    english_body = english.get_data(as_text=True)
    assert 'Everyone broadly agrees with this one.' in english_body
    assert french not in english_body
    assert 'data-reload-page' not in english_body


def test_report_and_axis_labels_use_cached_translations(app, db, client):
    """A French viewer sees the cached statement on the report and on the
    results-page axis label. Both requests are French, so the per-test locale
    pin does not hide a miss.
    """
    with app.app_context():
        discussion_id, owner_id, french = _seed_translated_report(db)

    _login(client, owner_id)
    report = client.get(f'/discussions/{discussion_id}/consensus/report?lang=fr')
    assert report.status_code == 200
    body = report.get_data(as_text=True)
    assert french in body
    assert 'Titre traduit du debat' in body
    assert 'Everyone broadly agrees with this one.' not in body
    # The weaker statement has no French cache row, so the pending notice shows
    # and its canonical text remains.
    assert 'A weaker agreement that must not lead the list.' in body
    assert 'data-reload-page' in body

    results = client.get(f'/discussions/{discussion_id}/consensus?lang=fr')
    assert results.status_code == 200
    results_body = results.get_data(as_text=True)
    assert results_body.count(french) >= 2
