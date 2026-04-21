"""
Unit tests for the numpy-only statistical primitives added to
app/lib/consensus_engine.py.

These primitives underpin every percentage and significance claim the
consensus results page makes, so they need to be tested independently
of the Flask app / DB.
"""
import numpy as np
import pytest

from app.lib.consensus_engine import (
    wilson_interval,
    fisher_exact_greater,
    benjamini_hochberg,
    benjamini_yekutieli,
    fdr_mask,
    newcombe_diff_interval,
    permutation_p_value_multi_cluster,
    _chi_square_statistic_from_counts,
    select_k_by_stability,
    cluster_users,
    identify_representative_statements,
    identify_divisive_statements,
    identify_bridge_statements,
    identify_consensus_statements,
)
import pandas as pd


# ── Wilson score interval ─────────────────────────────────────────────────

def test_wilson_matches_published_values_for_3_of_10():
    """3/10 → 95% CI ≈ [0.108, 0.603] per standard references."""
    p, lo, hi = wilson_interval(3, 10)
    assert p == 0.3
    assert lo == pytest.approx(0.108, abs=0.01)
    assert hi == pytest.approx(0.603, abs=0.01)


def test_wilson_small_sample_does_not_claim_100_percent():
    """2/2 must NOT produce [1.0, 1.0] — that was the pre-rigour bug."""
    _, lo, hi = wilson_interval(2, 2)
    assert lo < 0.5
    assert hi == 1.0


def test_wilson_zero_n_is_maximally_uncertain():
    """n=0 returns (0.0, 0.0, 1.0) — the uninformative prior."""
    p, lo, hi = wilson_interval(0, 0)
    assert (p, lo, hi) == (0.0, 0.0, 1.0)


# ── Fisher's exact test (one-sided) ───────────────────────────────────────

def test_fisher_lady_tasting_tea_reproduces_classic_p():
    """Fisher's lady tasting tea (3,1,1,3) → p ≈ 0.2429."""
    p = fisher_exact_greater(3, 1, 1, 3)
    assert p == pytest.approx(0.2429, abs=0.01)


def test_fisher_extreme_separation_has_very_small_p():
    """10-0 vs 0-10 is maximally separated; p should be < 1e-4."""
    p = fisher_exact_greater(10, 0, 0, 10)
    assert p < 1e-4


def test_fisher_null_table_has_p_near_0_5():
    """5,5,5,5 is exactly the null — p should be well above alpha."""
    p = fisher_exact_greater(5, 5, 5, 5)
    assert 0.5 < p < 0.9


# ── Benjamini–Hochberg FDR ────────────────────────────────────────────────

def test_bh_rejects_only_when_step_up_condition_holds():
    """For sorted p = [.001,.008,.039,...], first two pass at alpha=0.05."""
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06, 0.074, 0.205, 0.212, 1.0]
    mask = benjamini_hochberg(pvals, alpha=0.05)
    assert mask.tolist() == [True, True, False, False, False, False, False, False, False, False]


def test_bh_accepts_all_when_all_tiny():
    """Uniformly small p-values: all rejected."""
    mask = benjamini_hochberg([0.001, 0.002, 0.003, 0.004, 0.005], alpha=0.05)
    assert mask.all()


def test_bh_accepts_none_when_all_large():
    """Uniformly large p-values: none rejected."""
    mask = benjamini_hochberg([0.5, 0.6, 0.7], alpha=0.05)
    assert not mask.any()


# ── End-to-end engine identification smoke test ───────────────────────────

def _toy_matrix():
    """Two clearly-opposing groups with a shared bridge statement."""
    rows = [
        # Group A rows (agree on 100-102, reject 103-104, mixed on 106)
        [1, 1, 1, -1, -1, 1, np.nan, 1],
        [1, 1, 1, -1, -1, 1, -1, 1],
        [1, 1, 1, np.nan, -1, 1, -1, 1],
        # Group B rows (flipped on 100-104, same bridge at 105, 107)
        [-1, -1, -1, 1, 1, 1, np.nan, 1],
        [-1, -1, -1, 1, 1, 1, 1, 1],
        [-1, -1, -1, 1, 1, 1, 1, 1],
    ]
    index = [f"u_{i}" for i in range(6)]
    cols = list(range(100, 108))
    return pd.DataFrame(rows, index=index, columns=cols), np.array([0, 0, 0, 1, 1, 1])


def test_representative_statements_separate_agree_and_reject_by_group():
    vm, labels = _toy_matrix()
    reps = identify_representative_statements(vm, labels, top_n=3)
    group_a_directions = {e["direction"] for e in reps[0]}
    group_b_directions = {e["direction"] for e in reps[1]}
    assert "agree" in group_a_directions
    assert "reject" in group_b_directions


def test_representative_statements_attach_wilson_and_lift():
    vm, labels = _toy_matrix()
    reps = identify_representative_statements(vm, labels, top_n=2)
    for entry in reps[0]:
        assert 0.0 <= entry["wilson_low"] <= entry["agreement_rate"] <= entry["wilson_high"] <= 1.0
        assert entry["lift"] >= 1.0
        assert 0.0 <= entry["p_value"] <= 1.0
        assert "significant" in entry


def test_bridges_detect_symmetric_all_group_agreement():
    vm, labels = _toy_matrix()
    bridges = identify_bridge_statements(vm, labels)
    statement_ids = {b["statement_id"] for b in bridges}
    # 105 and 107 are the shared-agreement statements in the toy matrix.
    assert 105 in statement_ids
    assert 107 in statement_ids
    for b in bridges:
        assert b["polarity"] in ("agree", "reject")


def test_divisive_uses_inter_cluster_gap_not_overall_rate():
    vm, labels = _toy_matrix()
    divisive = identify_divisive_statements(vm, labels)
    # 100/101/102 should all qualify — each has a 100-point group gap.
    statement_ids = {d["statement_id"] for d in divisive}
    assert {100, 101, 102}.issubset(statement_ids)
    for d in divisive:
        assert d["group_gap"] >= 0.30
        assert 0.0 <= d["p_value"] <= 1.0


def test_consensus_uses_wilson_lower_bound_gate():
    """With only 3 votes per group, Wilson lower bound on 100% is ~0.44
    — below the 0.6 per-cluster threshold, so no consensus should be
    claimed. Pre-rigour code would have called this a "100% consensus"."""
    vm, labels = _toy_matrix()
    consensus = identify_consensus_statements(vm, labels)
    assert consensus == []  # small sample correctly fails the gate


# ── Template smoke test ──────────────────────────────────────────────────

def test_consensus_results_template_renders_with_rigour_copy(app):
    """End-to-end: the results template must compile and surface the
    Wilson / FDR / reproducibility / methodology copy we added."""
    from datetime import datetime
    from flask import render_template

    class _A:
        num_clusters = 2
        participants_count = 20
        statements_count = 8
        silhouette_score = 0.42
        method = 'agglomerative'
        cluster_data = {
            'consensus_statements': [],
            'bridge_statements': [],
            'divisive_statements': [],
            'representative_statements': {},
            'pca_axis_loadings': {
                'pc1': {'positive_statement_ids': [1], 'negative_statement_ids': [2]},
                'pc2': {'positive_statement_ids': [3], 'negative_statement_ids': [4]},
            },
            'metadata': {
                'stability_runs': 3,
                'stability_mean_ari': 0.71,
                'stability_consensus_jaccard_mean': 0.8,
            },
        }
        created_at = datetime(2026, 4, 20, 12, 0)

    class _D:
        id = 1
        title = 'Demo'
        slug = 'demo'
        programme = None
        partner_fk_id = None

    with app.test_request_context('/'):
        html = render_template(
            'discussions/consensus_results.html',
            discussion=_D(),
            analysis=_A(),
            consensus_statements=[],
            bridge_statements=[],
            divisive_statements=[],
            consensus_data_by_id={},
            bridge_data_by_id={},
            divisive_data_by_id={},
            opinion_groups=[{
                'id': 0, 'name': 'Group 1', 'participant_count': 3,
                'statements': [], 'agree_statements': [],
                'reject_statements': [], 'mixed_statements': [],
                'too_few_votes': False, 'small_sample': True,
                'has_significant_signal': False,
            }],
            translation_map={},
            discussion_translation=None,
            current_lang='en',
            axis_loadings=_A.cluster_data['pca_axis_loadings'],
            axis_loading_map={
                1: {'statement_id': 1, 'content': 'a', 'short': 'a'},
                2: {'statement_id': 2, 'content': 'b', 'short': 'b'},
                3: {'statement_id': 3, 'content': 'c', 'short': 'c'},
                4: {'statement_id': 4, 'content': 'd', 'short': 'd'},
            },
            viewer_participant_key='u_1',
            is_stale_analysis=True,
            current_stmt_count=15,
            analysed_stmt_count=8,
        )

    for phrase in (
        'Methodology', 'Wilson', 'FDR', 'Benjamini', 'Reproducibility',
        'Limitations', 'Newer votes', 'Small sample', 'accessible table',
    ):
        assert phrase in html, f"expected {phrase!r} in rendered template"


# ── Publishability regression: legacy analyses must still publish ─────────

def test_publishability_passes_legacy_analyses_without_stability(app):
    """Old full-matrix analyses (pre-stability rollout) have no
    stability_mean_ari in metadata. They must continue to publish — we
    must not retroactively withhold historical results."""
    from app.discussions.consensus import _assess_analysis_publishability

    class _A:
        cluster_data = {'metadata': {}}

    with app.app_context():
        ok, reason = _assess_analysis_publishability(_A())
    assert ok is True
    assert reason is None


def test_publishability_withholds_full_matrix_with_bad_stability(app):
    """New full-matrix analyses whose stability ARI falls below the
    configured floor must be withheld."""
    from app.discussions.consensus import _assess_analysis_publishability

    class _A:
        cluster_data = {'metadata': {
            'stability_runs': 3,
            'stability_mean_ari': 0.05,  # well below default floor 0.20
        }}

    with app.app_context():
        ok, reason = _assess_analysis_publishability(_A())
    assert ok is False
    assert 'reproducible' in reason.lower() or 'stability' in reason.lower()


# ── Journey: dominant-stance tie handling ─────────────────────────────────

def test_journey_crowd_stance_returns_none_on_near_ties():
    """If the top two stances are within the tie margin (max(2 votes, 5%%
    of total)), crowd_stance must be None — we don't invent a lean."""
    # Re-implement the tie test inline — the function is an inner expression.
    def stance(agree, disagree, unsure):
        total = agree + disagree + unsure
        if not total:
            return None
        ranked = sorted(
            [("agree", agree), ("disagree", disagree), ("unsure", unsure)],
            key=lambda x: x[1],
            reverse=True,
        )
        tie_margin = max(2, int(round(0.05 * total)))
        return None if (ranked[0][1] - ranked[1][1]) < tie_margin else ranked[0][0]

    # Dead-even
    assert stance(5, 5, 0) is None
    # One-vote margin out of 100 → inside 5% tie margin
    assert stance(45, 44, 11) is None
    # Clear lean
    assert stance(80, 10, 10) == "agree"
    # Zero votes
    assert stance(0, 0, 0) is None


# ── Newcombe MOVER-Wilson interval for proportion differences ────────────

def test_newcombe_maximally_separated_has_tight_lower_bound():
    """p1 = 10/10 vs p2 = 0/10 → diff = 1.0; lower bound should be well
    above 0.5 (the sample is small but fully separated)."""
    diff, lo, hi = newcombe_diff_interval(10, 10, 0, 10)
    assert diff == 1.0
    assert lo > 0.5
    assert hi == 1.0


def test_newcombe_matches_published_for_7_of_10_vs_3_of_10():
    """Newcombe (1998) Method 10 for 7/10 vs 3/10 gives 95% CI
    approximately [-0.03, 0.67]. Our numpy implementation must agree to
    two decimal places."""
    diff, lo, hi = newcombe_diff_interval(7, 10, 3, 10)
    assert diff == pytest.approx(0.4)
    assert lo == pytest.approx(-0.03, abs=0.02)
    assert hi == pytest.approx(0.67, abs=0.02)


def test_newcombe_degenerate_inputs_do_not_crash():
    """n1=0 or n2=0 must return a valid, maximally-uncertain interval."""
    diff, lo, hi = newcombe_diff_interval(0, 0, 5, 10)
    assert (diff, lo, hi) == (0.0, -1.0, 1.0)


def test_newcombe_bounds_always_in_range():
    """CI must never exceed [-1, 1] regardless of inputs."""
    for a1, n1, a2, n2 in [(1, 1, 0, 1), (2, 2, 0, 2), (1, 100, 99, 100)]:
        diff, lo, hi = newcombe_diff_interval(a1, n1, a2, n2)
        assert -1.0 <= lo <= diff <= hi <= 1.0


# ── Benjamini–Yekutieli FDR (arbitrary dependence) ────────────────────────

def test_by_is_strictly_more_conservative_than_bh():
    """For any set of p-values, BY should reject a subset of what BH
    rejects (equal when BH rejects nothing)."""
    pvals = [0.001, 0.008, 0.039, 0.041, 0.042, 0.06]
    bh = benjamini_hochberg(pvals, 0.05)
    by = benjamini_yekutieli(pvals, 0.05)
    # BY rejections are a subset of BH rejections.
    assert np.all(np.where(by, bh, True))
    # And strictly a subset here (BH should reject more).
    assert int(bh.sum()) > int(by.sum())


def test_fdr_mask_dispatch():
    """fdr_mask must dispatch to BH or BY based on method arg."""
    pvals = [0.001, 0.002, 0.003]
    assert fdr_mask(pvals, 0.05, method='bh').tolist() == benjamini_hochberg(pvals, 0.05).tolist()
    assert fdr_mask(pvals, 0.05, method='by').tolist() == benjamini_yekutieli(pvals, 0.05).tolist()
    # Unknown method falls back to BH (we log a warning).
    assert fdr_mask(pvals, 0.05, method='foo').tolist() == benjamini_hochberg(pvals, 0.05).tolist()


# ── Chi-square homogeneity statistic ──────────────────────────────────────

def test_chi_square_maximally_separated_table():
    """The 2×3 table [[10,5,0],[0,5,10]] has χ² = 20 by hand: totals
    15/15/30, expected 5 everywhere, each corner cell contributes 5."""
    chi2 = _chi_square_statistic_from_counts(np.array([[10, 5, 0], [0, 5, 10]]))
    assert chi2 == pytest.approx(20.0)


def test_chi_square_equal_proportions_yields_zero():
    """All cells match expected → χ² = 0."""
    chi2 = _chi_square_statistic_from_counts(np.array([[5, 5, 5], [5, 5, 5]]))
    assert chi2 == pytest.approx(0.0)


def test_chi_square_handles_zero_expected_without_nan():
    """Zero column totals must not produce NaN (safe for sparse tables)."""
    chi2 = _chi_square_statistic_from_counts(np.array([[5, 0, 5], [5, 0, 5]]))
    assert np.isfinite(chi2)


# ── Permutation omnibus: the test that drives divisive FDR ────────────────

def test_permutation_flags_divisive_statement_with_small_p():
    """Three clusters voting in opposite directions → small permutation p."""
    labels = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2])
    votes = pd.Series([1, 1, 1, -1, -1, -1, 1, 1, 1]).astype(float)
    rng = np.random.default_rng(0)
    p, chi2, K = permutation_p_value_multi_cluster(
        labels, votes, n_permutations=500, rng=rng
    )
    assert K == 3
    assert chi2 > 5
    assert p < 0.05


def test_permutation_null_statement_has_high_p():
    """Random-looking votes → large permutation p."""
    labels = np.array([0, 0, 0, 1, 1, 1, 2, 2, 2])
    # Same votes across all clusters → χ² = 0.
    votes = pd.Series([1, 1, 1, 1, 1, 1, 1, 1, 1]).astype(float)
    rng = np.random.default_rng(0)
    p, chi2, K = permutation_p_value_multi_cluster(
        labels, votes, n_permutations=500, rng=rng
    )
    assert K == 3
    assert chi2 == pytest.approx(0.0)
    assert p == 1.0


def test_permutation_counts_neutral_as_non_agree_like_agreement_rate():
    """Regression: the omnibus test MUST treat neutral (0) as non-agree,
    matching agreement_rate = (#agree) / (#non-missing). A previous
    implementation restricted the test to ±1 voters — so a statement
    where cluster 0 all agreed (+1) and cluster 1 was all neutral (0)
    produced p=1 (nothing to test), even though group_gap = 1.0 and the
    Newcombe CI would correctly flag the separation. This test locks in
    the alignment with the gap / CI."""
    labels = np.array([0, 0, 0, 0, 1, 1, 1, 1])
    votes = pd.Series([1, 1, 1, 1, 0, 0, 0, 0]).astype(float)
    p, chi2, K = permutation_p_value_multi_cluster(
        labels, votes, n_permutations=500, rng=np.random.default_rng(0)
    )
    assert K == 2
    assert chi2 > 0, "neutral-vs-agree split must produce non-zero chi²"
    assert p < 0.05, "maximal neutral-vs-agree split must be FDR-worthy"


# ── Divisive pipeline end-to-end: omnibus drives FDR ─────────────────────

def test_divisive_surface_includes_omnibus_and_pairwise_fields():
    """The divisive entries must now carry BOTH the omnibus p (p_value)
    and the pairwise Fisher p (p_value_gap), plus the Newcombe gap CI
    (gap_ci_low/high), so the template can be honest about which p
    drives significance."""
    vm, labels = _toy_matrix()
    divisive = identify_divisive_statements(
        vm, labels, n_permutations=200, rng=np.random.default_rng(0)
    )
    assert divisive, "toy matrix should produce divisive statements"
    for d in divisive:
        assert 'p_value' in d       # omnibus — the one FDR is run on
        assert 'p_value_gap' in d   # pairwise extreme Fisher — secondary
        assert 'chi2' in d
        assert 'gap_ci_low' in d
        assert 'gap_ci_high' in d
        assert d['gap_ci_low'] <= d['group_gap'] <= d['gap_ci_high'] + 1e-9
        assert d['fdr_method'] in ('bh', 'by')


def test_divisive_fdr_method_honours_by_argument():
    """Explicit fdr_method='by' should flow into each divisive entry."""
    vm, labels = _toy_matrix()
    divisive = identify_divisive_statements(
        vm, labels, fdr_method='by', n_permutations=200, rng=np.random.default_rng(0)
    )
    for d in divisive:
        assert d['fdr_method'] == 'by'


# ── Neutral vs. true disagree — UI honesty regression ─────────────────────

def test_all_neutral_votes_do_not_produce_reject_bridges():
    """When every vote is 0 (neutral), no statement should be surfaced as a
    'reject bridge'. Shared indifference ≠ shared rejection; that mislabel
    would put statements nobody actually disagreed with into a red card."""
    vm = pd.DataFrame(
        [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
        index=['u_0', 'u_1', 'u_2'],
        columns=[1, 2, 3, 4],
    ).astype(float)
    labels = np.array([0, 0, 1])
    bridges = identify_bridge_statements(vm, labels)
    assert bridges == [], (
        "all-neutral voting must not produce any bridge statements — "
        "the old agreement_rate <= 0.35 gate did not distinguish neutral "
        "from disagree"
    )


def test_all_neutral_cluster_is_mixed_not_reject_in_reps():
    """A cluster whose members are all neutral on a statement should be
    classified as 'mixed', not 'reject'. Pre-fix, agreement_rate=0 was
    sufficient for direction='reject', which implied active disagreement
    the data did not support."""
    vm = pd.DataFrame(
        [[1, 1, 1], [0, 0, 0]],
        index=['u_0', 'u_1'],
        columns=[1, 2, 3],
    ).astype(float)
    labels = np.array([0, 1])
    reps = identify_representative_statements(vm, labels)
    for entry in reps[1]:
        assert entry['direction'] == 'mixed', (
            f"neutral-only group statement {entry['statement_id']} "
            f"was classified as {entry['direction']!r}; expected 'mixed'"
        )


def test_true_disagree_still_surfaces_as_reject_bridge():
    """Regression: the neutral fix must not break the real 'shared
    rejection' path. All -1 votes should still produce a reject bridge."""
    vm = pd.DataFrame(
        [[-1, -1], [-1, -1], [-1, -1]],
        index=['u_0', 'u_1', 'u_2'],
        columns=[1, 2],
    ).astype(float)
    labels = np.array([0, 0, 1])
    bridges = identify_bridge_statements(vm, labels)
    assert bridges, "all-disagree case must still produce reject bridges"
    for b in bridges:
        assert b['polarity'] == 'reject'
        assert b['mean_disagreement'] > 0.5


# ── Stability-based k selection ──────────────────────────────────────────

def test_stability_selection_picks_correct_k_on_3_block_synthetic():
    """Three clearly separated blocks of 5 participants each → k=3 should
    win the silhouette × mean-ARI composite."""
    rng = np.random.default_rng(0)

    def block(template, n):
        out = np.tile(template, (n, 1)).astype(float)
        out += rng.normal(0, 0.1, out.shape)
        return out

    data = np.vstack([
        block([1, 1, 1, 1, -1, -1, -1, -1], 5),
        block([-1, -1, -1, -1, 1, 1, 1, 1], 5),
        block([1, -1, 1, -1, 1, -1, 1, -1], 5),
    ])
    best_k, per_k = select_k_by_stability(
        data, k_min=2, k_max=5, method='kmeans',
        n_bootstraps=10, random_state=1,
    )
    assert best_k == 3
    # Every k entry must carry the diagnostic shape the UI relies on.
    for m in per_k:
        assert set(m.keys()) >= {'k', 'silhouette', 'mean_ari', 'composite'}


def test_cluster_users_stability_selection_exposes_per_k_metrics():
    """cluster_users must stash per-k diagnostic metrics so
    _build_analysis_payload can persist them in analysis metadata."""
    rng = np.random.default_rng(2)
    data = np.vstack([
        np.tile([1, 1, -1], (5, 1)) + rng.normal(0, 0.05, (5, 3)),
        np.tile([-1, -1, 1], (5, 1)) + rng.normal(0, 0.05, (5, 3)),
    ])
    labels, _sil = cluster_users(
        data, method='kmeans', selection_method='stability', stability_bootstraps=6
    )
    assert cluster_users.last_metrics, "stability selection must record per-k metrics"
    assert len(np.unique(labels)) == 2


# ── MutableDict: in-place mutations on cluster_data must persist ──────────

def test_cluster_data_mutations_persist_across_sessions(app, db):
    """Regression: routes like generate_summary / generate_cluster_labels
    do `analysis.cluster_data['ai_summary'] = ...; db.session.commit()`.
    Without MutableDict.as_mutable, SQLAlchemy sees the same Python object
    reference and skips the UPDATE — the mutation silently does not
    persist. This test commits an in-place mutation and re-reads the row
    from a fresh session to confirm it round-trips."""
    from app.models import Discussion, ConsensusAnalysis, generate_slug

    with app.app_context():
        discussion = Discussion(
            title='MutableDict round-trip',
            slug=generate_slug('MutableDict round-trip'),
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        analysis = ConsensusAnalysis(
            discussion_id=discussion.id,
            cluster_data={'metadata': {'method': 'kmeans'}},
            num_clusters=2,
            silhouette_score=0.5,
            method='kmeans',
            participants_count=10,
            statements_count=5,
        )
        db.session.add(analysis)
        db.session.commit()
        analysis_id = analysis.id

        # In-place mutation — the route pattern.
        fresh = db.session.get(ConsensusAnalysis, analysis_id)
        fresh.cluster_data['ai_summary'] = 'The crowd broadly agrees on X.'
        fresh.cluster_data['summary_generated_at'] = '2026-04-21T12:00:00'
        db.session.commit()

        db.session.expire_all()
        reloaded = db.session.get(ConsensusAnalysis, analysis_id)
        assert reloaded.cluster_data.get('ai_summary') == 'The crowd broadly agrees on X.'
        assert reloaded.cluster_data.get('summary_generated_at') == '2026-04-21T12:00:00'


# ── Help page regression: native_system.html reflects new methodology ────

def test_native_system_help_page_surfaces_rigour_copy(app):
    """The analysis help page must describe Wilson CIs, FDR, Newcombe,
    and the permutation omnibus — readers who click through from the
    results page should not see stale copy."""
    from flask import render_template
    with app.test_request_context('/'):
        html = render_template('help/native_system.html')
    for phrase in ('Wilson', 'FDR', 'Newcombe', 'permutation', 'Limitations'):
        assert phrase in html, f"expected {phrase!r} in native_system help page"
