# app/lib/consensus_engine.py
"""
Consensus Clustering Engine (Phase 3)

Vote-based user clustering inspired by pol.is, with additions for academic
rigour: Wilson score intervals on every reported proportion, Fisher's exact
test for statement representativeness, Benjamini–Hochberg FDR correction
across the full (cluster × statement) test surface, and stability metrics
computed for every analysis (not just oversize).

Based on pol.is clustering patterns (AGPL-3.0).

Method references:
  - Small, C. T., Bjorkegren, M., Erkkilä, T., Shaw, L., & Megill, C. (2021).
    Polis: Scaling deliberation by mapping high dimensional opinion spaces.
    RECERCA. Revista de Pensament i Anàlisi. https://polis.shopify.com/papers
  - Wilson, E. B. (1927). Probable inference, the law of succession, and
    statistical inference. JASA 22(158), 209-212. (Score interval)
  - Benjamini, Y., & Hochberg, Y. (1995). Controlling the false discovery
    rate: a practical and powerful approach to multiple testing. JRSS-B 57(1),
    289-300.
  - Monti, S., Tamayo, P., Mesirov, J., & Golub, T. (2003). Consensus
    clustering: a resampling-based method for class discovery and
    visualization of gene expression microarray data. Machine Learning 52,
    91-118. (Stability-based cluster evaluation)
  - pol.is red-dwarf clustering library (AGPL-3.0):
    https://github.com/polis-community/red-dwarf  (sparsity-aware scaling)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from app.lib.time import utcnow_naive
from app.discussions.thresholds import (
    CONSENSUS_MIN_PARTICIPANTS,
    CONSENSUS_MIN_TOTAL_VOTES,
    CONSENSUS_MIN_VOTES_PER_STATEMENT,
)
from typing import Dict, List, Tuple, Optional
import logging

from app.lib.sklearn_compat import (
    SKLEARN_AVAILABLE,
    AgglomerativeClustering,
    KMeans,
    PCA,
    silhouette_score,
)

logger = logging.getLogger(__name__)


# ==============================================================================
# SPARSITY-AWARE SCALING (from pol.is red-dwarf)
# ==============================================================================
# Adapted from: https://github.com/polis-community/red-dwarf
# License: AGPL-3.0 (compatible with Society Speaks)
#
# This is a key innovation from pol.is that prevents participants with fewer
# votes from clustering near the center of PCA space. Without this, you get
# mostly 2-3 clusters. With it, you get more nuanced opinion groups (4-5+).
# ==============================================================================

def calculate_scaling_factors(vote_matrix_sparse):
    """
    Calculate row-based scaling factors from sparse vote matrix.

    Participants who voted on fewer statements get higher scaling factors,
    which stretches them away from the center in PCA space. This prevents
    sparse voters from being incorrectly grouped together.

    Formula: sqrt(total_statements / participant_votes)

    Example:
    - Voted on all 20 statements: sqrt(20/20) = 1.0 (no change)
    - Voted on 5 statements: sqrt(20/5) = 2.0 (doubled distance)
    - Voted on 2 statements: sqrt(20/2) = 3.16 (tripled distance)

    Args:
        vote_matrix_sparse: DataFrame with NaN for missing votes

    Returns:
        Array of scaling factors (one per participant)
    """
    # Convert DataFrame to numpy array for processing
    X_sparse = vote_matrix_sparse.values if isinstance(vote_matrix_sparse, pd.DataFrame) else vote_matrix_sparse
    X_sparse = np.atleast_2d(X_sparse)

    _, n_total_statements = X_sparse.shape

    # Count actual votes per participant (non-NaN values)
    vote_mask = ~np.isnan(X_sparse)
    n_participant_votes = np.count_nonzero(vote_mask, axis=1)

    # Calculate scaling: sqrt(total / actual_votes)
    # Use maximum(1, ...) to avoid division by zero
    scaling_factors = np.sqrt(n_total_statements / np.maximum(1, n_participant_votes))

    return scaling_factors


def apply_sparsity_scaling(pca_coordinates, vote_matrix_sparse):
    """
    Apply sparsity-aware scaling to PCA coordinates.

    This is the pol.is innovation that enables finding 4-5+ opinion groups
    instead of just 2-3. It stretches sparse voters away from the center
    proportionally to how sparse their voting is.

    Args:
        pca_coordinates: numpy array (n_participants, n_components)
        vote_matrix_sparse: DataFrame with NaN for missing votes

    Returns:
        Scaled PCA coordinates (same shape as input)
    """
    scaling_factors = calculate_scaling_factors(vote_matrix_sparse)

    # Apply scaling to each PCA dimension
    # scaling_factors[:, np.newaxis] converts (n,) to (n, 1) for broadcasting
    scaled_coordinates = pca_coordinates * scaling_factors[:, np.newaxis]

    logger.info(f"Applied sparsity scaling. Factor range: [{scaling_factors.min():.2f}, {scaling_factors.max():.2f}]")

    return scaled_coordinates


# ==============================================================================
# STATISTICAL PRIMITIVES (numpy-only; no scipy dependency)
# ==============================================================================
# Every proportion we surface to users is accompanied by a Wilson score
# interval. Representativeness uses Fisher + FDR (BH by default, optional BY).
# Divisiveness uses a permutation χ² omnibus test + FDR, with pairwise
# Fisher as a secondary gap check; see module docstring for references.
# ==============================================================================

# 95% CI by default; change via WILSON_Z if a different level is required.
WILSON_Z = 1.959963984540054  # norm.ppf(0.975)
FDR_ALPHA = 0.05


def wilson_interval(successes, n, z=WILSON_Z):
    """
    Wilson score confidence interval for a binomial proportion.

    More accurate than the normal approximation at small n and at extreme
    proportions, and never produces impossible bounds (e.g. negative or
    >1 probabilities). See Wilson (1927).

    Args:
        successes: number of "yes" outcomes
        n: total trials (must be >= 0)
        z: z-score for the desired confidence level (default 1.96 → 95%)

    Returns:
        (point_estimate, lower_bound, upper_bound) as floats in [0, 1].
        For n=0 returns (0.0, 0.0, 1.0) — the maximally-uncertain prior.
    """
    n = int(n)
    if n <= 0:
        return 0.0, 0.0, 1.0
    k = int(successes)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    margin = z * np.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return float(p), float(max(0.0, centre - margin)), float(min(1.0, centre + margin))


def _log_factorial_table(nmax):
    """Precomputed log-factorials 0..nmax via cumulative sum."""
    if nmax < 1:
        return np.array([0.0])
    return np.concatenate(([0.0], np.cumsum(np.log(np.arange(1, nmax + 1, dtype=np.float64)))))


def _log_hypergeom_pmf(k, K, n, N, logfact):
    """log P(X = k) where X ~ Hypergeometric(N, K, n)."""
    if k < 0 or k > K or (n - k) < 0 or (n - k) > (N - K):
        return -np.inf
    return (
        logfact[K] - logfact[k] - logfact[K - k]
        + logfact[N - K] - logfact[n - k] - logfact[N - K - (n - k)]
        - (logfact[N] - logfact[n] - logfact[N - n])
    )


def fisher_exact_greater(a, b, c, d):
    """
    One-sided Fisher's exact test for a 2x2 contingency table:

                        agree    disagree
        in-group          a         b
        out-of-group      c         d

    Tests H1: p(agree | in-group) > p(agree | out-of-group).

    Uses the hypergeometric distribution under the null of equal proportions.
    Returns the p-value as a float in [0, 1]. Numpy-only, no scipy.
    """
    a, b, c, d = int(a), int(b), int(c), int(d)
    if min(a, b, c, d) < 0:
        return 1.0
    N = a + b + c + d
    if N == 0:
        return 1.0
    K = a + b  # total in-group size
    n = a + c  # total "agree" column
    if K == 0 or n == 0:
        return 1.0
    logfact = _log_factorial_table(N)
    # Sum P(X = j) for j in [a, min(K, n)] in log-space with a max-trick.
    jmax = min(K, n)
    log_terms = np.array(
        [_log_hypergeom_pmf(j, K, n, N, logfact) for j in range(a, jmax + 1)],
        dtype=np.float64,
    )
    finite = log_terms[np.isfinite(log_terms)]
    if finite.size == 0:
        return 1.0
    m = finite.max()
    p = float(np.exp(m) * np.sum(np.exp(finite - m)))
    return float(min(1.0, max(0.0, p)))


def benjamini_hochberg(pvalues, alpha=FDR_ALPHA):
    """
    Benjamini–Hochberg FDR procedure. Returns a boolean mask of rejected
    hypotheses (True = significant at the given FDR level). See BH (1995).

    Equivalent to returning the largest prefix of BH-sorted p-values that
    all satisfy p(i) <= alpha * i / m.

    BH is valid under independence and under positive regression
    dependency (Benjamini & Yekutieli 2001). For arbitrary dependence use
    :func:`benjamini_yekutieli`, which is strictly more conservative.
    """
    p = np.asarray(pvalues, dtype=np.float64)
    m = p.size
    if m == 0:
        return np.zeros(0, dtype=bool)
    order = np.argsort(p)
    ranked = p[order]
    thresholds = alpha * np.arange(1, m + 1) / m
    passed = ranked <= thresholds
    if not np.any(passed):
        return np.zeros(m, dtype=bool)
    cutoff = int(np.max(np.where(passed)))
    rejected = np.zeros(m, dtype=bool)
    rejected[order[: cutoff + 1]] = True
    return rejected


def benjamini_yekutieli(pvalues, alpha=FDR_ALPHA):
    """
    Benjamini–Yekutieli (2001) FDR procedure — valid under *arbitrary*
    dependence between tests. Equivalent to BH with threshold divided by
    the m-th harmonic number c(m) = Σ_{k=1..m} 1/k.

    Strictly more conservative than BH. Preferred when correlated tests
    are expected — e.g. cluster-then-test settings where a single fitted
    clustering produces all the hypotheses we're screening.
    """
    p = np.asarray(pvalues, dtype=np.float64)
    m = p.size
    if m == 0:
        return np.zeros(0, dtype=bool)
    c_m = float(np.sum(1.0 / np.arange(1, m + 1)))
    return benjamini_hochberg(p, alpha / c_m)


def fdr_mask(pvalues, alpha=FDR_ALPHA, method='bh'):
    """Dispatch BH vs BY so call sites don't grow duplicated if/else."""
    m = (method or 'bh').lower()
    if m == 'by':
        return benjamini_yekutieli(pvalues, alpha)
    if m != 'bh':
        logger.warning("Unknown FDR method %r; falling back to BH", method)
    return benjamini_hochberg(pvalues, alpha)


# ── Newcombe (1998) Method 10: MOVER-Wilson interval for p1 - p2 ──────────

def newcombe_diff_interval(a1, n1, a2, n2, z=WILSON_Z):
    """
    Confidence interval for the difference of two independent binomial
    proportions (p1 - p2) using Newcombe's Method 10 — the "MOVER-Wilson"
    hybrid score interval. More accurate than naive bound-subtraction at
    small n or extreme proportions, and never produces bounds outside
    [-1, 1]. Reference: Newcombe (1998) Statistics in Medicine 17(8):
    873-890, Method 10.

    Returns (point_estimate, lower, upper). For n1=0 or n2=0 the point
    estimate is undefined; we return (0.0, -1.0, 1.0) — maximally
    uncertain.
    """
    n1 = int(n1)
    n2 = int(n2)
    if n1 <= 0 or n2 <= 0:
        return 0.0, -1.0, 1.0
    p1, l1, u1 = wilson_interval(a1, n1, z=z)
    p2, l2, u2 = wilson_interval(a2, n2, z=z)
    diff = p1 - p2
    lower = diff - np.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = diff + np.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return float(diff), float(max(-1.0, lower)), float(min(1.0, upper))


# ── Chi-square + permutation: multi-cluster divisive test (no post-selection)

def _chi_square_statistic_from_counts(counts_2xK):
    """
    Pearson chi-square statistic for a 2×K contingency table. Zero-
    expectation cells contribute zero (safe for small or sparse tables).
    """
    counts = np.asarray(counts_2xK, dtype=np.float64)
    if counts.ndim != 2 or counts.shape[0] != 2 or counts.shape[1] < 2:
        return 0.0
    row_totals = counts.sum(axis=1, keepdims=True)
    col_totals = counts.sum(axis=0, keepdims=True)
    grand_total = float(counts.sum())
    if grand_total <= 0:
        return 0.0
    expected = row_totals @ col_totals / grand_total
    with np.errstate(divide='ignore', invalid='ignore'):
        diff2 = (counts - expected) ** 2
        contribs = np.where(expected > 0, diff2 / expected, 0.0)
    return float(contribs.sum())


def permutation_p_value_multi_cluster(
    cluster_labels,
    statement_votes,
    n_permutations=1000,
    rng=None,
):
    """
    Permutation p-value for "agreement rate differs across clusters" on a
    single statement.

    Builds a 2×K table (agree vs non-agree × cluster) using the same
    non-missing denominator as :func:`_per_cluster_agree_counts`:

        agreement_rate = (# agree) / (# non-missing votes)

    so "non-agree" counts disagree (−1) AND neutral/unsure (0) among voters.
    This alignment matters: if we tested only ±1 votes, the FDR-screened
    omnibus would be a *different* hypothesis than the ``group_gap`` and
    Newcombe CI shown next to it.

    Under the null (independence of agree-status and cluster), shuffling
    labels among voters leaves the marginals fixed and the joint
    distribution of agree-counts-per-cluster is multivariate hypergeometric.
    We therefore draw ``n_permutations`` samples from that distribution
    directly — equivalent to explicit label shuffling but O(B·K) instead
    of O(B·K·N), so oversize analyses and stability loops stay cheap.
    Uses add-one smoothing on the p-value to avoid 0/B pathologies.

    Args:
        cluster_labels: numpy array aligned with vote-matrix rows
        statement_votes: pandas Series of votes for one statement
        n_permutations: Monte Carlo budget (default 1000)
        rng: optional numpy Generator for determinism

    Returns:
        (p_value, chi2_observed, K_voting_clusters)
    """
    votes = np.asarray(statement_votes.values if hasattr(statement_votes, 'values') else statement_votes)
    labels = np.asarray(cluster_labels)
    voted_mask = ~np.isnan(votes.astype(float))
    if not voted_mask.any():
        return 1.0, 0.0, 0
    voted_votes = votes[voted_mask]
    voted_labels = labels[voted_mask]
    unique_clusters, label_idx = np.unique(voted_labels, return_inverse=True)
    K = int(unique_clusters.size)
    if K < 2:
        return 1.0, 0.0, K

    is_agree = (voted_votes == 1)
    cluster_sizes = np.bincount(label_idx, minlength=K).astype(np.int64)
    agree_per_cluster_obs = np.bincount(label_idx[is_agree], minlength=K).astype(np.int64)

    N_total = int(cluster_sizes.sum())
    agree_total = int(is_agree.sum())
    non_agree_total = N_total - agree_total
    if agree_total == 0 or non_agree_total == 0 or N_total == 0:
        # Degenerate: no between-cluster variation is possible on this row.
        return 1.0, 0.0, K

    # Pre-compute fixed marginals / expected cells. Under the null, both row
    # and column totals are preserved by the permutation, so the expected
    # cell counts are the same for every permutation.
    row_totals = np.array([agree_total, non_agree_total], dtype=np.float64)
    col_totals = cluster_sizes.astype(np.float64)
    expected = np.outer(row_totals, col_totals) / float(N_total)  # (2, K)
    exp_agree = expected[0]
    exp_non = expected[1]

    observed_2xK = np.vstack([
        agree_per_cluster_obs,
        cluster_sizes - agree_per_cluster_obs,
    ]).astype(np.float64)
    chi2_obs = _chi_square_statistic_from_counts(observed_2xK)
    if chi2_obs <= 0.0:
        return 1.0, 0.0, K

    if rng is None:
        rng = np.random.default_rng(seed=42)
    B = int(n_permutations)
    if B < 1:
        return 1.0, float(chi2_obs), K

    # Vectorised Monte Carlo: draw B × K matrices of agree-counts under the
    # multivariate hypergeometric implied by shuffling labels with fixed
    # agree_total and cluster_sizes.
    agree_perm = rng.multivariate_hypergeometric(cluster_sizes, agree_total, size=B)
    non_agree_perm = cluster_sizes[np.newaxis, :] - agree_perm  # (B, K)

    with np.errstate(divide='ignore', invalid='ignore'):
        term_a = np.where(exp_agree > 0, (agree_perm - exp_agree) ** 2 / exp_agree, 0.0)
        term_n = np.where(exp_non > 0, (non_agree_perm - exp_non) ** 2 / exp_non, 0.0)
    chi2_perms = (term_a + term_n).sum(axis=1)  # (B,)

    at_or_above = int(np.sum(chi2_perms >= chi2_obs))
    p = (at_or_above + 1) / (B + 1)
    return float(p), float(chi2_obs), K


def build_vote_matrix(discussion_id, db):
    """
    Build vote matrix from statement votes
    Rows = participants (users + anonymous), Columns = statements, Values = votes (-1, 0, 1)

    Supports both authenticated and anonymous participants:
    - Authenticated: identified by user_id (u_{id})
    - Anonymous: identified by session_fingerprint (a_{fingerprint})

    Returns:
        vote_matrix_filled: pandas DataFrame with filled values (for PCA/clustering)
        vote_matrix_real: pandas DataFrame with only real votes, NaN for missing (for consensus metrics)
        participant_ids: list of participant identifiers
        statement_ids: list of statement IDs
    """
    from app.models import StatementVote, Statement
    
    # Get all votes for this discussion (authenticated + anonymous), only on non-deleted statements
    votes = db.session.query(
        StatementVote.user_id,
        StatementVote.session_fingerprint,
        StatementVote.statement_id,
        StatementVote.vote
    ).join(Statement, StatementVote.statement_id == Statement.id).filter(
        StatementVote.discussion_id == discussion_id,
        Statement.is_deleted.is_(False)
    ).all()
    
    if not votes:
        return None, None, [], []
    
    # Create participant identifier: user_id takes precedence, fall back to session_fingerprint
    vote_data = []
    for v in votes:
        if v.user_id:
            participant_id = f"u_{v.user_id}"
        elif v.session_fingerprint:
            participant_id = f"a_{v.session_fingerprint[:16]}"
        else:
            continue  # Skip votes with neither identifier
        vote_data.append({
            'participant_id': participant_id,
            'statement_id': v.statement_id,
            'vote': v.vote
        })
    
    if not vote_data:
        return None, None, [], []
    
    # Convert to DataFrame
    df = pd.DataFrame(vote_data)
    
    # Pivot to create matrix (without filling initially)
    vote_matrix_real = df.pivot_table(
        index='participant_id',
        columns='statement_id',
        values='vote',
        aggfunc='mean'  # In case of duplicate votes (shouldn't happen)
    )

    # Create filled version for PCA/clustering
    # Fill missing votes with statement means (pol.is approach)
    # This preserves vote distribution instead of artificially inflating neutral votes
    # Example: If statement has 80% agree, 20% disagree - missing votes filled with 0.6
    statement_means = vote_matrix_real.mean(axis=0)
    vote_matrix_filled = vote_matrix_real.fillna(statement_means)

    # Fallback: if any statement has zero votes (shouldn't happen due to can_cluster check)
    vote_matrix_filled = vote_matrix_filled.fillna(0)

    participant_ids = vote_matrix_filled.index.tolist()
    statement_ids = vote_matrix_filled.columns.tolist()

    logger.info(f"Built vote matrix: {len(participant_ids)} participants x {len(statement_ids)} statements")
    means_list = statement_means.tolist()  # type: ignore[union-attr]
    if means_list:
        logger.info(f"Statement mean fill range: [{min(means_list):.2f}, {max(means_list):.2f}]")

    # Return both: filled for PCA, real for consensus metrics
    return vote_matrix_filled, vote_matrix_real, participant_ids, statement_ids


def can_cluster(discussion_id, db):
    """
    Check if discussion has enough data for meaningful clustering
    
    Criteria (from pol.is analysis):
    - At least CONSENSUS_MIN_PARTICIPANTS participants (users + anonymous)
    - At least CONSENSUS_MIN_TOTAL_VOTES total votes
    - Each statement has at least CONSENSUS_MIN_VOTES_PER_STATEMENT votes
    """
    plan = get_consensus_execution_plan(discussion_id, db)
    if not plan['is_ready']:
        return False, plan['message']
    if plan['mode'] != 'full_matrix':
        return False, plan['message']
    return True, "Ready for clustering"


def get_consensus_execution_plan(discussion_id, db):
    """
    Build an execution plan for consensus analysis.

    Modes:
    - full_matrix: regular PCA + clustering path
    - sampled_incremental: oversized fallback path
    """
    from flask import current_app
    from app.models import StatementVote, Statement
    from sqlalchemy import case, func
    
    # Count unique participants (user_id OR session_fingerprint) who voted on non-deleted statements
    participant_count = db.session.query(
        func.count(func.distinct(
            case(
                (StatementVote.user_id.isnot(None), func.concat('u_', StatementVote.user_id)),
                else_=func.concat('a_', StatementVote.session_fingerprint)
            )
        ))
    ).join(Statement, StatementVote.statement_id == Statement.id).filter(
        StatementVote.discussion_id == discussion_id,
        Statement.is_deleted.is_(False)
    ).scalar() or 0
    
    # Count statements
    statement_count = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    ).count()
    
    # Count total votes on non-deleted statements
    vote_count = db.session.query(StatementVote.id).join(
        Statement, StatementVote.statement_id == Statement.id
    ).filter(
        StatementVote.discussion_id == discussion_id,
        Statement.is_deleted.is_(False)
    ).count()
    
    # Check minimum votes per statement — LEFT JOIN so statements with zero votes
    # are included; otherwise a zero-vote statement would be silently skipped.
    votes_per_statement = db.session.query(
        Statement.id,
        db.func.count(StatementVote.id).label('vote_count')
    ).outerjoin(
        StatementVote,
        db.and_(
            StatementVote.statement_id == Statement.id,
            StatementVote.discussion_id == discussion_id
        )
    ).filter(
        Statement.discussion_id == discussion_id,
        Statement.is_deleted.is_(False)
    ).group_by(Statement.id).all()

    if not votes_per_statement:
        return {'is_ready': False, 'mode': 'not_ready', 'message': "No statements yet"}

    min_votes = min(v[1] for v in votes_per_statement)
    
    # Apply minimum readiness criteria first.
    if participant_count < CONSENSUS_MIN_PARTICIPANTS:
        return {
            'is_ready': False,
            'mode': 'not_ready',
            'message': (
                f"Need at least {CONSENSUS_MIN_PARTICIPANTS} participants "
                f"(have {participant_count})"
            ),
        }
    if vote_count < CONSENSUS_MIN_TOTAL_VOTES:
        return {
            'is_ready': False,
            'mode': 'not_ready',
            'message': (
                f"Need at least {CONSENSUS_MIN_TOTAL_VOTES} votes "
                f"(have {vote_count})"
            ),
        }
    if min_votes < CONSENSUS_MIN_VOTES_PER_STATEMENT:
        return {
            'is_ready': False,
            'mode': 'not_ready',
            'message': (
                "Some statements have fewer than "
                f"{CONSENSUS_MIN_VOTES_PER_STATEMENT} votes"
            ),
        }

    # Oversize guardrails for discussion-level safety caps.
    max_votes_for_full = current_app.config.get('MAX_CONSENSUS_FULL_MATRIX_VOTES', 500000)
    max_statements_for_full = current_app.config.get('MAX_CONSENSUS_FULL_MATRIX_STATEMENTS', 2000)
    max_participants_for_sync = current_app.config.get('MAX_SYNC_ANALYTICS_PARTICIPANTS', 50000)
    oversized_reasons = []
    if vote_count > max_votes_for_full:
        oversized_reasons.append(
            f"votes={vote_count} exceeds cap={max_votes_for_full}"
        )
    if statement_count > max_statements_for_full:
        oversized_reasons.append(
            f"statements={statement_count} exceeds cap={max_statements_for_full}"
        )
    if participant_count > max_participants_for_sync:
        oversized_reasons.append(
            f"participants={participant_count} exceeds cap={max_participants_for_sync}"
        )

    if oversized_reasons:
        return {
            'is_ready': True,
            'mode': 'sampled_incremental',
            'message': (
                "Oversize mode required. Running sampled/incremental strategy with precomputed aggregates "
                f"({'; '.join(oversized_reasons)})."
            ),
            'metrics': {
                'participants_count': participant_count,
                'statements_count': statement_count,
                'votes_count': vote_count,
            },
            'thresholds': {
                'max_votes_for_full': max_votes_for_full,
                'max_statements_for_full': max_statements_for_full,
                'max_participants_for_sync': max_participants_for_sync,
            }
        }

    return {
        'is_ready': True,
        'mode': 'full_matrix',
        'message': "Ready for full-matrix clustering",
        'metrics': {
            'participants_count': participant_count,
            'statements_count': statement_count,
            'votes_count': vote_count,
        },
        'thresholds': {
            'max_votes_for_full': max_votes_for_full,
            'max_statements_for_full': max_statements_for_full,
            'max_participants_for_sync': max_participants_for_sync,
        }
    }


def _sample_participant_ids_for_oversize(participant_vote_counts, max_participants, seed):
    """
    Deterministically sample participants while preserving high-activity signal.

    Strategy:
    - Keep a deterministic "head" of the most-active participants.
    - Fill remaining slots by weighted random sample from the long tail.
    """
    ranked = sorted(
        participant_vote_counts.items(),
        key=lambda item: item[1],
        reverse=True,
    )
    if len(ranked) <= max_participants:
        return [pid for pid, _ in ranked], {
            'participant_sampling_strategy': 'full_population',
            'deterministic_head_count': len(ranked),
            'tail_sample_count': 0,
        }

    head_count = min(max(500, max_participants // 3), len(ranked), 5000)
    head_ids = [pid for pid, _ in ranked[:head_count]]
    tail = ranked[head_count:]
    remaining_slots = max(0, max_participants - len(head_ids))

    if remaining_slots == 0 or not tail:
        return head_ids[:max_participants], {
            'participant_sampling_strategy': 'deterministic_head_only',
            'deterministic_head_count': min(len(head_ids), max_participants),
            'tail_sample_count': 0,
        }

    tail_ids = [pid for pid, _ in tail]
    # sqrt weighting reduces dominance of super-voters while preserving activity signal.
    weights = np.array([max(1.0, float(votes)) ** 0.5 for _, votes in tail], dtype=float)
    if weights.sum() <= 0:
        probabilities = None
    else:
        probabilities = weights / weights.sum()

    rng = np.random.default_rng(seed=seed)
    sample_count = min(remaining_slots, len(tail_ids))
    sampled_indices = rng.choice(
        len(tail_ids),
        size=sample_count,
        replace=False,
        p=probabilities,
    )
    sampled_tail_ids = [tail_ids[int(i)] for i in sampled_indices]
    sampled_ids = head_ids + sampled_tail_ids

    return sampled_ids, {
        'participant_sampling_strategy': 'head_plus_weighted_tail',
        'deterministic_head_count': len(head_ids),
        'tail_sample_count': len(sampled_tail_ids),
    }


def build_oversize_consensus_results(discussion_id, db, plan):
    """
    Oversize consensus pipeline for very large discussions.

    Instead of a naive fixed split, this path computes a sampled participant
    matrix, applies the same PCA + sparsity scaling + clustering pattern used
    in full-matrix mode, and clearly marks output as approximate.
    """
    from flask import current_app
    from app.models import Statement, StatementVote

    max_sampled_statements = int(
        current_app.config.get('MAX_CONSENSUS_OVERSIZE_SAMPLE_STATEMENTS', 500)
    )
    max_sampled_participants = int(
        current_app.config.get('MAX_CONSENSUS_OVERSIZE_SAMPLE_PARTICIPANTS', 5000)
    )

    statement_rows = db.session.query(
        Statement.id,
        Statement.vote_count_agree,
        Statement.vote_count_disagree,
        Statement.vote_count_unsure,
    ).filter(
        Statement.discussion_id == discussion_id,
        Statement.is_deleted.is_(False),
    ).all()
    if not statement_rows:
        return None

    scored = []
    for row in statement_rows:
        agree = int(row.vote_count_agree or 0)
        disagree = int(row.vote_count_disagree or 0)
        unsure = int(row.vote_count_unsure or 0)
        total = agree + disagree + unsure
        decisive = agree + disagree
        agreement_rate = (agree / decisive) if decisive > 0 else 0.0
        controversy_score = (1.0 - abs(agreement_rate - 0.5) * 2.0) if decisive > 0 else 0.0
        scored.append({
            'statement_id': int(row.id),
            'agreement_rate': float(agreement_rate),
            'mean_agreement': float(agreement_rate),
            'variance': 0.0,
            'controversy_score': float(controversy_score),
            'agree_rate': float(agreement_rate),
            'total_votes': int(total),
        })

    top_statement_ids = [
        s['statement_id']
        for s in sorted(scored, key=lambda x: x['total_votes'], reverse=True)[:max_sampled_statements]
    ]
    if not top_statement_ids:
        return None

    sampled_votes = db.session.query(
        StatementVote.user_id,
        StatementVote.session_fingerprint,
        StatementVote.statement_id,
        StatementVote.vote,
    ).filter(
        StatementVote.discussion_id == discussion_id,
        StatementVote.statement_id.in_(top_statement_ids),
    ).all()
    if not sampled_votes:
        return None

    vote_data = []
    participant_vote_counts = {}
    for vote in sampled_votes:
        if vote.user_id:
            participant_id = f"u_{vote.user_id}"
        elif vote.session_fingerprint:
            participant_id = f"a_{vote.session_fingerprint[:16]}"
        else:
            continue
        participant_vote_counts[participant_id] = participant_vote_counts.get(participant_id, 0) + 1
        vote_data.append(
            {
                'participant_id': participant_id,
                'statement_id': int(vote.statement_id),
                'vote': int(vote.vote),
            }
        )

    sampled_participant_ids, sampling_meta = _sample_participant_ids_for_oversize(
        participant_vote_counts=participant_vote_counts,
        max_participants=max_sampled_participants,
        seed=int(discussion_id),
    )
    if not sampled_participant_ids:
        return None

    sample_df = pd.DataFrame(vote_data)
    sample_df = sample_df[sample_df['participant_id'].isin(sampled_participant_ids)]
    if sample_df.empty:
        return None

    vote_matrix_real = sample_df.pivot_table(
        index='participant_id',
        columns='statement_id',
        values='vote',
        aggfunc='mean',
    )
    vote_matrix_real = vote_matrix_real.reindex(columns=top_statement_ids)

    # Drop columns with no sampled votes and keep a minimally informative matrix.
    sampled_vote_counts = vote_matrix_real.notna().sum(axis=0)
    usable_columns = sampled_vote_counts[sampled_vote_counts > 0].index.tolist()
    if len(usable_columns) < 2:
        return None
    vote_matrix_real = vote_matrix_real[usable_columns]

    statement_means = vote_matrix_real.mean(axis=0)
    vote_matrix_filled = vote_matrix_real.fillna(statement_means).fillna(0)

    sampled_user_ids = vote_matrix_real.index.tolist()
    base_results, _, _, user_labels = _build_analysis_payload(
        user_ids=sampled_user_ids,
        statement_ids=usable_columns,
        vote_matrix_filled=vote_matrix_filled,
        vote_matrix_real=vote_matrix_real,
        method='kmeans',
        random_state=int(discussion_id),
    )
    if base_results is None:
        return None

    stability_runs = int(current_app.config.get('CONSENSUS_OVERSIZE_STABILITY_RUNS', 5))
    stability_metrics = _compute_stability_metrics(
        vote_matrix_filled=vote_matrix_filled,
        vote_matrix_real=vote_matrix_real,
        baseline_labels=user_labels,
        baseline_consensus=base_results['consensus_statements'],
        baseline_bridge=base_results['bridge_statements'],
        baseline_divisive=base_results['divisive_statements'],
        method='kmeans',
        base_seed=int(discussion_id),
        run_count=stability_runs,
    )

    base_results['metadata'].update({
        'method': 'sampled_incremental_clustered',
        'participants_count': int(plan['metrics']['participants_count']),
        'statements_count': int(plan['metrics']['statements_count']),
        'oversize_mode': True,
        'oversize_reason': plan['message'],
        'oversize_thresholds': plan.get('thresholds', {}),
        'sampled_statement_count': int(len(usable_columns)),
        'sampled_participant_count': int(len(sampled_user_ids)),
        'sampled_vote_count': int(len(sample_df)),
        'participant_sampling_seed': int(discussion_id),
        'publication_min_stability_runs': int(
            current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_RUNS', 3)
        ),
        'publication_min_stability_mean_ari': float(
            current_app.config.get('CONSENSUS_OVERSIZE_MIN_STABILITY_ARI', 0.30)
        ),
        **sampling_meta,
        **stability_metrics,
    })
    return base_results


def _numpy_pca(matrix, n_components=2):
    """
    Pure-numpy PCA fallback when sklearn is unavailable.
    Returns (transformed_matrix, explained_variance_ratios).
    """
    centered = matrix - np.mean(matrix, axis=0)
    cov = np.cov(centered, rowvar=False)
    eigenvalues, eigenvectors = np.linalg.eigh(cov)
    # eigh returns ascending order; reverse for descending
    idx = np.argsort(eigenvalues)[::-1][:n_components]
    components = eigenvectors[:, idx]
    transformed = centered @ components
    total_var = np.sum(eigenvalues)
    explained_ratios = eigenvalues[idx] / total_var if total_var > 0 else np.zeros(n_components)
    return transformed, explained_ratios


def perform_pca(vote_matrix, n_components=2):
    """
    Perform PCA dimensionality reduction
    Pol.is uses 2 components for visualization

    NOTE: We do NOT use StandardScaler before PCA because:
    - Variance in voting data is meaningful (consensus vs. division)
    - StandardScaler would erase this signal by normalizing all statements to std=1
    - PCA should focus on high-variance (divisive) statements to find opinion groups
    - Cosine distance clustering doesn't require standardization anyway
    """
    class _PCAResult:
        def __init__(self, ratios):
            self.explained_variance_ratio_ = ratios

    if not SKLEARN_AVAILABLE:
        matrix = np.array(vote_matrix)
        transformed, explained_ratios = _numpy_pca(matrix, n_components)
        logger.info(f"Numpy PCA explained variance: {explained_ratios}")
        logger.info(f"Numpy PCA components shape: {transformed.shape}")
        return transformed, _PCAResult(explained_ratios)

    try:
        pca = PCA(n_components=n_components)
        vote_matrix_pca = pca.fit_transform(vote_matrix)
        logger.info(f"PCA explained variance: {pca.explained_variance_ratio_}")
        logger.info(f"PCA components shape: {vote_matrix_pca.shape}")
        return vote_matrix_pca, pca
    except (OSError, ImportError) as e:
        logger.error(f"sklearn PCA runtime failed ({e}), using numpy fallback")
        matrix = np.array(vote_matrix)
        transformed, explained_ratios = _numpy_pca(matrix, n_components)
        logger.info(f"Numpy PCA explained variance: {explained_ratios}")
        logger.info(f"Numpy PCA components shape: {transformed.shape}")
        return transformed, _PCAResult(explained_ratios)


def _numpy_cosine_distance_matrix(data):
    """Compute pairwise cosine distance matrix using numpy."""
    norms = np.linalg.norm(data, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1, norms)
    normed = data / norms
    sim = np.dot(normed, normed.T)
    return 1 - np.clip(sim, -1, 1)


def _numpy_silhouette(data, labels):
    """Compute mean silhouette score using cosine distance (numpy fallback)."""
    dist = _numpy_cosine_distance_matrix(data)
    unique_labels = np.unique(labels)
    if len(unique_labels) < 2:
        return 0.0
    n = len(labels)
    scores = np.zeros(n)
    for i in range(n):
        same = labels == labels[i]
        same[i] = False
        if same.sum() == 0:
            scores[i] = 0.0
            continue
        a = dist[i][same].mean()
        b_vals = []
        for lbl in unique_labels:
            if lbl == labels[i]:
                continue
            other = labels == lbl
            if other.sum() > 0:
                b_vals.append(dist[i][other].mean())
        b = min(b_vals) if b_vals else 0.0
        scores[i] = (b - a) / max(a, b) if max(a, b) > 0 else 0.0
    return float(np.mean(scores))


def _numpy_agglomerative(data, n_clusters):
    """Simple average-linkage agglomerative clustering using numpy with cosine distance."""
    dist = _numpy_cosine_distance_matrix(data)
    n = len(data)
    # Each point starts in its own cluster
    labels = list(range(n))
    # Track which points belong to each cluster
    clusters = {i: [i] for i in range(n)}

    while len(clusters) > n_clusters:
        # Find closest pair of clusters (average linkage)
        best_dist = float('inf')
        best_pair = (0, 1)
        cluster_ids = list(clusters.keys())
        for ci in range(len(cluster_ids)):
            for cj in range(ci + 1, len(cluster_ids)):
                id_a, id_b = cluster_ids[ci], cluster_ids[cj]
                pts_a, pts_b = clusters[id_a], clusters[id_b]
                avg_d = np.mean([dist[a][b] for a in pts_a for b in pts_b])
                if avg_d < best_dist:
                    best_dist = avg_d
                    best_pair = (id_a, id_b)
        # Merge
        merge_into, merge_from = best_pair
        clusters[merge_into].extend(clusters[merge_from])
        del clusters[merge_from]

    # Assign final labels
    final_labels = np.zeros(n, dtype=int)
    for new_label, (_, pts) in enumerate(clusters.items()):
        for p in pts:
            final_labels[p] = new_label
    return final_labels


def _cluster_at_k(data, k, method='agglomerative', random_state=42):
    """
    Single-shot clustering at a fixed k, returning (labels, silhouette).

    Centralises the sklearn-with-numpy-fallback boilerplate so every caller
    (initial fit, stability re-seeds, k selection bootstraps) goes through
    the same path — guarantees identical behaviour whether sklearn is
    available or not.
    """
    data = np.asarray(data)
    use_sklearn = SKLEARN_AVAILABLE
    if use_sklearn:
        try:
            if method == 'agglomerative':
                clusterer = AgglomerativeClustering(
                    n_clusters=k, linkage='average', metric='cosine'
                )
            else:
                clusterer = KMeans(n_clusters=k, random_state=random_state)
            labels = clusterer.fit_predict(data)
            score = silhouette_score(data, labels, metric='cosine')
            return labels, float(score)
        except (OSError, ImportError) as e:
            logger.error(
                "sklearn clustering runtime failed (%s); using numpy fallback", e
            )
    labels = _numpy_agglomerative(data, k)
    score = _numpy_silhouette(data, labels)
    return labels, float(score)


def select_k_by_stability(
    vote_matrix_pca,
    k_min=2,
    k_max=10,
    method='agglomerative',
    n_bootstraps=20,
    subsample_frac=0.8,
    random_state=42,
    rng=None,
):
    """
    Bootstrap-stability k selection (Monti-inspired; not the full
    consensus-matrix / CDF-AUC machine).

    For each candidate k, draw `n_bootstraps` participant subsamples
    (without replacement, size = subsample_frac × N), re-cluster each
    subsample at that k, and measure the Adjusted Rand Index between the
    subsample's labels and the baseline labels restricted to the same
    rows. Higher mean ARI = more reproducible k.

    We pick k maximising ``silhouette(k) × mean_ARI(k)`` — requires both
    good separation AND reproducibility. Silhouette alone over-rewards
    k=2; mean-ARI alone over-rewards trivial solutions. The product is a
    pragmatic stability-aware composite (related in spirit to Monti et
    al. 2003 consensus clustering and Tibshirani & Walther 2005 stability
    selection, without materialising a full N×N consensus matrix —
    attractive as a future upgrade when the bootstrap budget is larger).

    Returns:
        (best_k, per_k_metrics) where per_k_metrics is a list of dicts
        with keys k, silhouette, mean_ari, composite, n_bootstraps.
    """
    n = len(vote_matrix_pca)
    max_k = min(k_max, n // 2)
    if max_k < k_min:
        return k_min, []
    if rng is None:
        rng = np.random.default_rng(seed=random_state)

    sub_n = max(k_max + 1, int(round(subsample_frac * n)))
    per_k = []
    for k in range(k_min, max_k + 1):
        baseline_labels, silhouette = _cluster_at_k(
            vote_matrix_pca, k, method, random_state
        )
        aris = []
        for b in range(int(n_bootstraps)):
            if sub_n >= n:
                # Full-sample "bootstrap" — only useful for kmeans (reseed).
                idx = np.arange(n)
            else:
                idx = rng.choice(n, size=sub_n, replace=False)
                idx.sort()
            seed_b = int(random_state + b + 1)
            sub_labels, _ = _cluster_at_k(vote_matrix_pca[idx], k, method, seed_b)
            ari = _adjusted_rand_index(baseline_labels[idx], sub_labels)
            aris.append(ari)
        mean_ari = float(np.mean(aris)) if aris else 1.0
        # Composite: silhouette can be negative for bad clusterings; clip to
        # [0, 1] so the product doesn't flip sign and reward pathologies.
        composite = max(0.0, silhouette) * max(0.0, mean_ari)
        per_k.append({
            'k': int(k),
            'silhouette': float(silhouette),
            'mean_ari': mean_ari,
            'composite': float(composite),
            'n_bootstraps': int(n_bootstraps),
        })
        logger.info(
            "k=%d: silhouette=%.3f mean_ARI=%.3f composite=%.3f",
            k, silhouette, mean_ari, composite,
        )

    best = max(per_k, key=lambda m: (m['composite'], m['silhouette']))
    logger.info(
        "Stability-selected k=%d (silhouette=%.3f, mean_ARI=%.3f)",
        best['k'], best['silhouette'], best['mean_ari'],
    )
    return best['k'], per_k


def cluster_users(
    vote_matrix_pca,
    n_clusters=None,
    method='agglomerative',
    random_state=42,
    selection_method='silhouette',
    stability_bootstraps=20,
    rng=None,
):
    """
    Cluster users based on PCA-reduced vote matrix.

    When ``n_clusters`` is None we pick k automatically. Two selection
    methods are supported:

    - ``silhouette`` (default, fast): maximise silhouette over k ∈ [2, 10].
      Back-compat behaviour.
    - ``stability``: maximise silhouette × mean-ARI under bootstrap
      subsampling (Monti-inspired bootstrap stability; see
      :func:`select_k_by_stability` for the exact composite). More
      expensive, but makes the *chosen k* itself reproducible, not just
      the partition at the chosen k. Suitable for strict peer-review
      mode. Not the full consensus-matrix / AUC-of-CDF procedure.

    Returns (labels, silhouette). If ``selection_method='stability'`` the
    per-k diagnostic metrics are attached to ``cluster_users.last_metrics``
    (read by _build_analysis_payload to persist them in analysis metadata).
    """
    n = len(vote_matrix_pca)
    cluster_users.last_metrics = []

    if n_clusters is None:
        max_clusters = min(10, n // 2)
        if max_clusters < 2:
            logger.warning("Not enough users for clustering")
            return np.zeros(n), 0.0

        if selection_method == 'stability':
            n_clusters, per_k = select_k_by_stability(
                vote_matrix_pca,
                k_min=2,
                k_max=max_clusters,
                method=method,
                n_bootstraps=stability_bootstraps,
                random_state=random_state,
                rng=rng,
            )
            cluster_users.last_metrics = per_k
        else:
            best_score = -np.inf
            best_k = 2
            per_k = []
            for k in range(2, max_clusters + 1):
                _, score = _cluster_at_k(vote_matrix_pca, k, method, random_state)
                logger.info(f"k={k}: silhouette={score:.3f}")
                per_k.append({'k': int(k), 'silhouette': float(score)})
                if score > best_score:
                    best_score = score
                    best_k = k
            n_clusters = best_k
            cluster_users.last_metrics = per_k
            logger.info(f"Selected {n_clusters} clusters (silhouette={best_score:.3f})")

    labels, silhouette = _cluster_at_k(vote_matrix_pca, n_clusters, method, random_state)
    return labels, silhouette


# Ensure attribute is always defined so _build_analysis_payload can read it
# without a hasattr dance on the first call.
cluster_users.last_metrics = []


def _per_cluster_agree_counts(statement_votes, vote_matrix_index, user_labels):
    """
    Yield one dict per cluster with voting counts on a single statement.

    Shared by consensus / bridge / divisive identification so the vote-
    tabulation logic lives in exactly one place. Clusters that produced
    zero real votes on this statement are returned with n=0; callers
    filter them as needed.

    Yields dicts with:
      cluster_id (int)
      agree (int)            — votes of +1
      disagree (int)         — non-agree (i.e. n - agree, includes neutral).
                               Kept under this name for back-compat with
                               the Fisher extreme-pair test, which wants an
                               agree-vs-non-agree 2×2.
      disagree_strict (int)  — votes of -1 (pure disagreement, excludes neutral)
      neutral (int)          — votes of 0 (unsure/neutral)
      n (int)                — total non-missing votes
      agreement_rate (float) — agree / n
      disagree_rate (float)  — disagree_strict / n (for "shared rejection"
                               decisions; avoids misclassifying indifference
                               as rejection)
    """
    for cluster_id in np.unique(user_labels):
        cluster_mask = user_labels == cluster_id
        cluster_votes = statement_votes[vote_matrix_index[cluster_mask]]
        n = int(cluster_votes.notna().sum())
        a = int((cluster_votes == 1).sum())
        d = int((cluster_votes == -1).sum())
        yield {
            'cluster_id': int(cluster_id),
            'agree': a,
            'disagree': n - a,
            'disagree_strict': d,
            'neutral': n - a - d,
            'n': n,
            'agreement_rate': (a / n) if n > 0 else 0.0,
            'disagree_rate': (d / n) if n > 0 else 0.0,
        }


def identify_consensus_statements(vote_matrix, user_labels, consensus_threshold=0.7, cluster_threshold=0.6):
    """
    Identify statements with broad consensus across all opinion groups.

    Criteria (pol.is convention, tightened with Wilson small-sample guard):
      - Overall agreement Wilson lower bound ≥ consensus_threshold, **not**
        the raw rate. 7/10 agreement should not qualify as "70% consensus"
        when its 95% CI lower bound is only 40%.
      - Every cluster has voted on the statement AND its own agreement
        Wilson lower bound ≥ cluster_threshold.

    Returns a list ranked by overall Wilson lower bound (safest-signal first).
    Each entry carries: statement_id, agreement_rate, wilson_low, wilson_high,
    agree_count, disagree_count, vote_count, cluster_agreements.
    """
    consensus_statements = []
    n_clusters = len(np.unique(user_labels))

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]
        agree_votes = int((statement_votes == 1).sum())
        real_votes = statement_votes.notna()
        total_votes = int(real_votes.sum())
        if total_votes == 0:
            continue

        overall_rate, overall_low, overall_high = wilson_interval(agree_votes, total_votes)
        if overall_low < consensus_threshold:
            continue

        cluster_agreements = []
        passes_per_cluster = True
        for row in _per_cluster_agree_counts(statement_votes, vote_matrix.index, user_labels):
            if row['n'] == 0:
                passes_per_cluster = False
                break
            _, c_low, _ = wilson_interval(row['agree'], row['n'])
            if c_low < cluster_threshold:
                passes_per_cluster = False
                break
            cluster_agreements.append(row['agreement_rate'])

        if not passes_per_cluster or len(cluster_agreements) != n_clusters:
            continue

        consensus_statements.append({
            'statement_id': int(statement_id),
            'agreement_rate': float(overall_rate),
            'wilson_low': float(overall_low),
            'wilson_high': float(overall_high),
            'agree_count': agree_votes,
            'disagree_count': total_votes - agree_votes,
            'vote_count': total_votes,
            'cluster_agreements': cluster_agreements,
        })

    consensus_statements.sort(key=lambda s: s['wilson_low'], reverse=True)
    logger.info(f"Found {len(consensus_statements)} consensus statements (Wilson-gated)")
    return consensus_statements


def identify_bridge_statements(vote_matrix, user_labels, min_agreement=0.65, max_variance=0.15):
    """
    Identify bridge statements — those every opinion group agrees on (or
    every opinion group rejects). Symmetric bridges matter because a
    shared rejection is just as much common ground as a shared agreement.

    Criteria:
      - Every cluster has voted.
      - Variance between cluster rates ≤ max_variance (the groups agree
        with *each other* about this statement).
      - Either mean agreement across clusters ≥ min_agreement (shared
        agreement), OR mean *strict disagreement* (vote == -1 only) across
        clusters ≥ min_agreement (shared rejection).

    IMPORTANT: shared rejection is evaluated on the strict disagree rate
    (disagree_strict / n), not on 1 - agreement_rate. A statement on which
    every cluster is 100% neutral would otherwise be classified as a
    shared-rejection bridge — that's indifference, not common ground.

    Returns a list of dicts with: statement_id, mean_agreement,
    mean_disagreement, variance, cluster_agreements, polarity
    ('agree'|'reject'), agree_count, disagree_count, vote_count,
    wilson_low, wilson_high.
    """
    bridge_statements = []
    n_clusters = len(np.unique(user_labels))
    min_disagreement = min_agreement

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]

        rows = [
            row
            for row in _per_cluster_agree_counts(statement_votes, vote_matrix.index, user_labels)
            if row['n'] > 0
        ]
        if len(rows) < 2 or len(rows) != n_clusters:
            continue

        cluster_agreements = [r['agreement_rate'] for r in rows]
        cluster_disagreements = [r['disagree_rate'] for r in rows]

        mean_agreement = float(np.mean(cluster_agreements))
        mean_disagreement = float(np.mean(cluster_disagreements))
        variance_agree = float(np.var(cluster_agreements))
        variance_disagree = float(np.var(cluster_disagreements))

        agree_votes = int((statement_votes == 1).sum())
        disagree_strict_total = int((statement_votes == -1).sum())
        total_votes = int(statement_votes.notna().sum())
        non_agree_votes = total_votes - agree_votes

        if mean_agreement >= min_agreement and variance_agree <= max_variance:
            polarity = 'agree'
            variance_for_polarity = variance_agree
            _, w_low, w_high = wilson_interval(agree_votes, total_votes)
        elif mean_disagreement >= min_disagreement and variance_disagree <= max_variance:
            polarity = 'reject'
            variance_for_polarity = variance_disagree
            _, w_low, w_high = wilson_interval(disagree_strict_total, total_votes)
        else:
            continue

        bridge_statements.append({
            'statement_id': int(statement_id),
            'mean_agreement': mean_agreement,
            'mean_disagreement': mean_disagreement,
            'variance': variance_for_polarity,
            'cluster_agreements': cluster_agreements,
            'cluster_disagreements': cluster_disagreements,
            'polarity': polarity,
            'agree_count': agree_votes,
            # 'disagree_count' kept as non-agree (n - a) so existing CSV
            # exports / JSON readers don't shift meaning; 'disagree_strict_count'
            # exposes the -1-only figure for anyone who wants it.
            'disagree_count': non_agree_votes,
            'disagree_strict_count': disagree_strict_total,
            'vote_count': total_votes,
            'wilson_low': float(w_low),
            'wilson_high': float(w_high),
        })

    bridge_statements.sort(key=lambda s: (s['wilson_low'], -s['variance']), reverse=True)
    logger.info(
        "Found %d bridge statements (agree=%d, reject=%d)",
        len(bridge_statements),
        sum(1 for b in bridge_statements if b['polarity'] == 'agree'),
        sum(1 for b in bridge_statements if b['polarity'] == 'reject'),
    )
    return bridge_statements


def identify_divisive_statements(
    vote_matrix,
    user_labels,
    min_group_gap=0.30,
    min_cluster_votes=3,
    fdr_method='bh',
    n_permutations=1000,
    rng=None,
):
    """
    Identify statements that divide the opinion groups.

    A statement is divisive when *different groups vote differently*, not
    merely when the overall population splits 50/50 (which can be pure
    noise). For each statement we:

      1. Compute agreement rate per cluster among those who voted.
      2. Require at least two clusters to have ≥ min_cluster_votes real
         votes on the statement.
      3. Measure inter-cluster variance and the max-vs-min agreement gap.
      4. Run a **permutation-based omnibus test** — shuffle cluster labels
         among voters, recompute Pearson χ² for the 2×K table, and take
         the fraction of permutations at least as extreme as observed.
         This is the pre-specified, all-cluster test that FDR is applied
         to; it does not depend on post-selecting extreme clusters.
      5. Also run one-sided Fisher on the max-vs-min pair as a small-
         sample secondary check that the *displayed gap* is not a fluke.
      6. CI on the gap uses Newcombe (1998) MOVER-Wilson Method 10.

    FDR correction (BH by default; BY when ``fdr_method='by'`` for
    arbitrary-dependence guarantees) is applied to the omnibus p-values.

    Statistical caveats (for interpretation):
      - Clustering is fit on the same votes — inference is exploratory.
      - The pairwise Fisher p is a post-hoc check on the displayed gap,
        not a simultaneous test. It is surfaced as ``p_value_gap``.
      - The ``p_value`` field drives the FDR decision and is the omnibus
        permutation statistic, which is pre-specified per statement.

    Returns:
        List of dicts with keys:
        statement_id, agree_rate, controversy_score, variance, group_gap,
        gap_ci_low, gap_ci_high, wilson_low, wilson_high (aliases of the
        gap CI for backward compat), max_agreement, min_agreement,
        max_cluster_id, min_cluster_id, cluster_agreements, p_value
        (omnibus), p_value_gap (pairwise Fisher), chi2, significant,
        fdr_method.
    """
    candidates = []
    pvals = []
    user_labels_arr = np.asarray(user_labels)
    if rng is None:
        rng = np.random.default_rng(seed=42)

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]

        # Per-cluster agreement with minimum-vote threshold.
        per_cluster = [
            row
            for row in _per_cluster_agree_counts(statement_votes, vote_matrix.index, user_labels)
            if row['n'] >= min_cluster_votes
        ]

        if len(per_cluster) < 2:
            continue

        rates = [c['agreement_rate'] for c in per_cluster]
        max_c = max(per_cluster, key=lambda c: c['agreement_rate'])
        min_c = min(per_cluster, key=lambda c: c['agreement_rate'])
        gap = max_c['agreement_rate'] - min_c['agreement_rate']
        if gap < min_group_gap:
            continue

        variance = float(np.var(rates))
        # Legacy "controversy" (overall 50/50 split) retained for backward
        # compatibility with existing CSV exports and old callers.
        agree_votes = int((statement_votes == 1).sum())
        disagree_votes = int((statement_votes == -1).sum())
        total_votes = agree_votes + disagree_votes
        agree_rate = (agree_votes / total_votes) if total_votes > 0 else 0.0
        controversy = 1.0 - abs(agree_rate - 0.5) * 2.0

        # Omnibus permutation p-value — the FDR-controlled test.
        p_omnibus, chi2_obs, _k_obs = permutation_p_value_multi_cluster(
            cluster_labels=user_labels_arr,
            statement_votes=statement_votes,
            n_permutations=n_permutations,
            rng=rng,
        )
        # Pairwise Fisher on the extreme pair — a post-hoc check on the
        # displayed gap, surfaced as a secondary signal.
        p_pairwise = fisher_exact_greater(
            max_c['agree'], max_c['disagree'],
            min_c['agree'], min_c['disagree'],
        )

        # Newcombe MOVER-Wilson CI for the gap (proper difference CI).
        _, gap_lo, gap_hi = newcombe_diff_interval(
            max_c['agree'], max_c['n'], min_c['agree'], min_c['n']
        )
        # Legacy fields (wilson_low/high) retained for existing template
        # + CSV consumers; they now hold the Newcombe bounds so the
        # numbers improve without anyone having to migrate field names.
        wilson_low = float(max(0.0, gap_lo))
        wilson_high = float(min(1.0, gap_hi))

        candidates.append({
            'statement_id': int(statement_id),
            'agree_rate': float(agree_rate),
            'controversy_score': float(controversy),
            'variance': variance,
            'group_gap': float(gap),
            'gap_ci_low': wilson_low,
            'gap_ci_high': wilson_high,
            # Back-compat aliases for older template / CSV consumers.
            'wilson_low': wilson_low,
            'wilson_high': wilson_high,
            'max_agreement': float(max_c['agreement_rate']),
            'min_agreement': float(min_c['agreement_rate']),
            'max_cluster_id': max_c['cluster_id'],
            'min_cluster_id': min_c['cluster_id'],
            'cluster_agreements': [c['agreement_rate'] for c in per_cluster],
            'p_value': float(p_omnibus),
            'p_value_gap': float(p_pairwise),
            'chi2': float(chi2_obs),
            'fdr_method': fdr_method,
        })
        pvals.append(p_omnibus)

    # Apply FDR (BH or BY) across all candidates on the omnibus p-values.
    if candidates:
        sig_mask = fdr_mask(np.array(pvals), alpha=FDR_ALPHA, method=fdr_method)
        for c, s in zip(candidates, sig_mask):
            c['significant'] = bool(s)
        # Rank significant divisive statements above non-significant,
        # within each tier by gap lower bound (Newcombe) then omnibus p.
        candidates.sort(
            key=lambda c: (c['significant'], c['gap_ci_low'], -c['p_value']),
            reverse=True,
        )

    logger.info(
        "Divisive: %d candidate statements (%d FDR-significant at q=%.2f)",
        len(candidates),
        sum(1 for c in candidates if c.get('significant')),
        FDR_ALPHA,
    )
    return candidates


REPRESENTATIVE_DIRECTION_AGREE_THRESHOLD = 0.60
REPRESENTATIVE_DIRECTION_REJECT_THRESHOLD = 0.40


def _classify_direction(agreement_rate, disagree_rate=None):
    """
    Dead-zone ternary classification for representativeness.

    Near-even splits (40–60%) get 'mixed' rather than being forced into
    'agree' or 'reject' — a 51/49 statement tells a reader nothing about
    the group's defining beliefs.

    When ``disagree_rate`` (strict: vote == -1) is provided, "reject" is
    gated on actual strict disagreement rather than just "below the agree
    threshold". A 100%-neutral statement has agreement_rate=0 but
    disagree_rate=0 — that's *indifference*, not rejection, and should
    render as 'mixed'.
    """
    if agreement_rate >= REPRESENTATIVE_DIRECTION_AGREE_THRESHOLD:
        return 'agree'
    if disagree_rate is not None:
        if disagree_rate >= REPRESENTATIVE_DIRECTION_AGREE_THRESHOLD:
            return 'reject'
        return 'mixed'
    # Back-compat fallback for callers that don't supply disagree_rate.
    if agreement_rate <= REPRESENTATIVE_DIRECTION_REJECT_THRESHOLD:
        return 'reject'
    return 'mixed'


def identify_representative_statements(vote_matrix, user_labels, top_n=5, fdr_method='bh'):
    """
    Identify representative statements for each opinion group.

    A *representative* statement is one a group holds more firmly than the
    rest of the participants — not merely one they hold strongly on its own.
    We therefore score each (cluster, statement) pair by:

      1. **Lift** (pol.is "repness"): P(agree | in-group) / P(agree | out-group)
         — both for agreement and for rejection (symmetric). Lift > 1 means
         the in-group's stance distinguishes them from everyone else.
      2. **One-sided Fisher's exact test** on the 2×2 contingency table:
         tests whether the in/out-group difference is larger than chance
         given small cell counts. No normal-approximation assumption.
      3. **FDR correction** (Benjamini–Hochberg by default, Benjamini–Yekutieli
         when ``fdr_method='by'``) applied across ALL (cluster × statement)
         tests in the analysis. Statements flagged `significant=True` survive
         correction at q = 0.05.
      4. **Wilson 95% CI** reported on the in-group agreement rate so the
         template can render "67% (95% CI 41–86%)" rather than a bare
         percentage.

    The final ranking multiplies lift by the Wilson lower bound so noisy
    small-sample extremes don't out-rank well-evidenced moderate signals.

    Args:
        vote_matrix: DataFrame with real votes (NaN for missing)
        user_labels: cluster assignments for each participant
        top_n: number of statements to return per group

    Returns:
        Dict[int, List[dict]] — cluster_id → ranked list. Each dict carries
        statement_id, agreement_rate, wilson_low, wilson_high, agree_count,
        disagree_count, vote_count, out_agreement_rate, lift, p_value,
        significant, direction ('agree'|'reject'|'mixed'), strength.
    """
    representatives = {}
    pending = []  # collected per (cluster, statement) for global FDR

    unique_clusters = np.unique(user_labels)
    for cluster_id in unique_clusters:
        cluster_mask = user_labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        out_indices = np.where(~cluster_mask)[0]
        cluster_votes = vote_matrix.iloc[cluster_indices]
        out_votes = vote_matrix.iloc[out_indices] if out_indices.size > 0 else None

        group_size = len(cluster_indices)
        min_votes_needed = max(1, min(3, (group_size + 1) // 2))

        for statement_id in cluster_votes.columns:
            in_col = cluster_votes[statement_id]
            in_real = in_col.notna()
            vote_count = int(in_real.sum())
            if vote_count < min_votes_needed:
                continue

            agree_count = int((in_col == 1).sum())
            disagree_count = vote_count - agree_count  # non-agree (includes neutral)
            disagree_strict = int((in_col == -1).sum())
            agreement_rate = agree_count / vote_count
            disagree_rate_strict = disagree_strict / vote_count

            # Out-of-group counts (may be empty for k=1 degenerate case).
            if out_votes is not None:
                out_col = out_votes[statement_id]
                out_agree = int((out_col == 1).sum())
                out_total = int(out_col.notna().sum())
            else:
                out_agree = 0
                out_total = 0
            out_rate = (out_agree / out_total) if out_total > 0 else 0.0

            # Symmetric lift: whichever direction is stronger for this group
            # determines the test. +0.5 pseudo-count (Haldane) guards against
            # zero-division while barely moving non-degenerate estimates.
            eps = 0.5
            lift_agree = ((agree_count + eps) / (vote_count + 2 * eps)) / (
                (out_agree + eps) / (out_total + 2 * eps) if out_total > 0 else 0.5
            )
            lift_reject = ((disagree_count + eps) / (vote_count + 2 * eps)) / (
                ((out_total - out_agree) + eps) / (out_total + 2 * eps) if out_total > 0 else 0.5
            )

            if lift_reject > lift_agree:
                # Test: in-group disagrees more than out-group.
                p_value = fisher_exact_greater(
                    disagree_count, agree_count,
                    out_total - out_agree, out_agree,
                )
                lift = float(lift_reject)
                tested_direction = 'reject'
            else:
                p_value = fisher_exact_greater(
                    agree_count, disagree_count,
                    out_agree, out_total - out_agree,
                )
                lift = float(lift_agree)
                tested_direction = 'agree'

            _, wilson_low, wilson_high = wilson_interval(agree_count, vote_count)

            # Rank by lift × Wilson lower bound of the *tested* direction so
            # that well-evidenced differences outrank noisy small-sample ones.
            if tested_direction == 'reject':
                _, reject_low, _ = wilson_interval(disagree_count, vote_count)
                ranking_evidence = reject_low
            else:
                ranking_evidence = wilson_low
            strength = float(lift * ranking_evidence)

            entry = {
                'statement_id': int(statement_id),
                'agreement_rate': float(agreement_rate),
                'disagree_rate': float(disagree_rate_strict),
                'wilson_low': float(wilson_low),
                'wilson_high': float(wilson_high),
                'vote_count': vote_count,
                'agree_count': agree_count,
                'disagree_count': disagree_count,  # non-agree (backwards compat)
                'disagree_strict_count': disagree_strict,
                'out_agreement_rate': float(out_rate),
                'out_vote_count': out_total,
                'lift': lift,
                'p_value': float(p_value),
                'direction': _classify_direction(agreement_rate, disagree_rate_strict),
                'tested_direction': tested_direction,
                'strength': strength,
            }
            pending.append((int(cluster_id), entry))

    # Global FDR correction across the whole (cluster × statement) surface.
    if pending:
        pvals = np.array([e['p_value'] for _, e in pending], dtype=np.float64)
        sig_mask = fdr_mask(pvals, alpha=FDR_ALPHA, method=fdr_method)
        for (cid, entry), is_sig in zip(pending, sig_mask):
            entry['significant'] = bool(is_sig)
            representatives.setdefault(cid, []).append(entry)

    for cid in list(representatives.keys()):
        representatives[cid].sort(
            key=lambda x: (x['significant'], x['strength']),
            reverse=True,
        )
        representatives[cid] = representatives[cid][:top_n]

    # Fill empty clusters so downstream code can still iterate all of them.
    for cluster_id in unique_clusters:
        representatives.setdefault(int(cluster_id), [])

    total = sum(len(v) for v in representatives.values())
    sig_total = sum(1 for v in representatives.values() for e in v if e.get('significant'))
    logger.info(
        "Representativeness: %d statements across %d groups (%d FDR-significant at q=%.2f)",
        total, len(representatives), sig_total, FDR_ALPHA,
    )
    return representatives


def _statement_id_set(statement_records):
    return {int(item['statement_id']) for item in statement_records}


def _jaccard_similarity(a, b):
    if not a and not b:
        return 1.0
    union = a | b
    if not union:
        return 1.0
    return len(a & b) / len(union)


def _adjusted_rand_index(labels_a, labels_b):
    """
    Adjusted Rand Index (ARI) implemented with numpy only.
    """
    a = np.asarray(labels_a)
    b = np.asarray(labels_b)
    if a.shape[0] != b.shape[0]:
        return 0.0
    n = int(a.shape[0])
    if n < 2:
        return 1.0

    _, inv_a = np.unique(a, return_inverse=True)
    _, inv_b = np.unique(b, return_inverse=True)
    n_a = int(inv_a.max()) + 1
    n_b = int(inv_b.max()) + 1
    contingency = np.zeros((n_a, n_b), dtype=np.int64)
    for idx in range(n):
        contingency[inv_a[idx], inv_b[idx]] += 1

    def comb2(x):
        x = np.asarray(x, dtype=np.float64)
        return x * (x - 1.0) / 2.0

    sum_nij = float(comb2(contingency).sum())
    sum_ai = float(comb2(contingency.sum(axis=1)).sum())
    sum_bj = float(comb2(contingency.sum(axis=0)).sum())
    total_pairs = float(comb2(np.array([n]))[0])
    if total_pairs <= 0:
        return 1.0

    expected = (sum_ai * sum_bj) / total_pairs
    max_index = 0.5 * (sum_ai + sum_bj)
    denom = max_index - expected
    if denom == 0:
        return 1.0
    return float((sum_nij - expected) / denom)


def _pca_axis_loadings(pca, statement_ids, top_n=3):
    """
    Identify the statements that most strongly define PC1 and PC2.

    For each component, return the top_n statements with the largest
    positive loading and the top_n with the largest negative loading, so
    the UI can annotate axes with "← Agrees: 'X' │ Agrees: 'Y' →" rather
    than a bare "Principal Component 1".
    """
    components = getattr(pca, 'components_', None)
    if components is None or len(statement_ids) == 0:
        return {}
    out = {}
    for axis_idx, axis_name in enumerate(('pc1', 'pc2')):
        if axis_idx >= components.shape[0]:
            break
        loadings = components[axis_idx]
        order = np.argsort(loadings)
        positive_ids = [int(statement_ids[i]) for i in order[::-1][:top_n]]
        negative_ids = [int(statement_ids[i]) for i in order[:top_n]]
        out[axis_name] = {
            'positive_statement_ids': positive_ids,
            'negative_statement_ids': negative_ids,
            'positive_loadings': [float(loadings[i]) for i in order[::-1][:top_n]],
            'negative_loadings': [float(loadings[i]) for i in order[:top_n]],
        }
    return out


def _resolve_fdr_method():
    """Read `CONSENSUS_FDR_METHOD` from Flask config if an app context is
    available; fall back to 'bh'. Kept in one place so the engine and the
    methodology UI never drift on which FDR procedure was actually used."""
    try:
        from flask import current_app
        return str(current_app.config.get('CONSENSUS_FDR_METHOD', 'bh') or 'bh').lower()
    except Exception:
        return 'bh'


def _resolve_k_selection_method():
    """
    Read `CONSENSUS_K_SELECTION_METHOD` from Flask config. 'silhouette'
    (default, fast) or 'stability' (Monti-style). Kept with the other
    resolvers so the engine and methodology UI can't drift.
    """
    try:
        from flask import current_app
        return str(current_app.config.get('CONSENSUS_K_SELECTION_METHOD', 'silhouette') or 'silhouette').lower()
    except Exception:
        return 'silhouette'


def _resolve_permutation_budget():
    """Permutation budget for the divisive omnibus χ² (default 1000)."""
    try:
        from flask import current_app
        return int(current_app.config.get('CONSENSUS_PERMUTATION_BUDGET', 1000) or 1000)
    except Exception:
        return 1000


def _resolve_stability_bootstraps():
    """Bootstrap count used by stability-based k selection (default 20)."""
    try:
        from flask import current_app
        return int(current_app.config.get('CONSENSUS_K_STABILITY_BOOTSTRAPS', 20) or 20)
    except Exception:
        return 20


def _build_analysis_payload(user_ids, statement_ids, vote_matrix_filled, vote_matrix_real, method='agglomerative', random_state=42):
    """
    Shared analysis pipeline used by full-matrix and oversize modes.
    """
    if vote_matrix_filled is None or len(user_ids) == 0:
        return None, None, None, None

    fdr_method = _resolve_fdr_method()
    k_selection_method = _resolve_k_selection_method()
    permutation_budget = _resolve_permutation_budget()
    stability_bootstraps = _resolve_stability_bootstraps()

    vote_matrix_pca, pca = perform_pca(vote_matrix_filled)
    vote_matrix_pca_scaled = apply_sparsity_scaling(vote_matrix_pca, vote_matrix_real)
    user_labels, silhouette = cluster_users(
        vote_matrix_pca_scaled,
        method=method,
        random_state=random_state,
        selection_method=k_selection_method,
        stability_bootstraps=stability_bootstraps,
    )
    # Capture the per-k diagnostic metrics cluster_users stashed on itself
    # so we can expose them (transparency: reviewers can see why this k).
    k_selection_metrics = list(cluster_users.last_metrics or [])

    cluster_assignments = {
        user_id: int(label)
        for user_id, label in zip(user_ids, user_labels)
    }
    pca_coordinates = {
        user_id: (float(coords[0]), float(coords[1]))
        for user_id, coords in zip(user_ids, vote_matrix_pca_scaled)
    }

    consensus_stmts = identify_consensus_statements(vote_matrix_real, user_labels)
    bridge_stmts = identify_bridge_statements(vote_matrix_real, user_labels)
    divisive_stmts = identify_divisive_statements(
        vote_matrix_real,
        user_labels,
        fdr_method=fdr_method,
        n_permutations=permutation_budget,
    )
    representative_stmts = identify_representative_statements(
        vote_matrix_real, user_labels, fdr_method=fdr_method
    )
    axis_loadings = _pca_axis_loadings(pca, statement_ids)

    results = {
        'cluster_assignments': cluster_assignments,
        'pca_coordinates': pca_coordinates,
        'consensus_statements': consensus_stmts,
        'bridge_statements': bridge_stmts,
        'divisive_statements': divisive_stmts,
        'representative_statements': representative_stmts,
        'pca_axis_loadings': axis_loadings,
        'k_selection': {
            'method': k_selection_method,
            'per_k_metrics': k_selection_metrics,
        },
        'metadata': {
            'num_clusters': int(len(np.unique(user_labels))),
            'silhouette_score': float(silhouette),
            'method': method,
            'participants_count': len(user_ids),
            'statements_count': len(statement_ids),
            'analyzed_at': utcnow_naive().isoformat(),
            'explained_variance': pca.explained_variance_ratio_.tolist(),
            # Statistical methodology surfaced alongside results so that
            # downstream audits and academic reviewers can see exactly how
            # we produced the reported numbers.
            'wilson_z': WILSON_Z,
            'fdr_alpha': FDR_ALPHA,
            'fdr_method': fdr_method,
            'k_selection_method': k_selection_method,
            'permutation_budget': permutation_budget,
            'direction_agree_threshold': REPRESENTATIVE_DIRECTION_AGREE_THRESHOLD,
            'direction_reject_threshold': REPRESENTATIVE_DIRECTION_REJECT_THRESHOLD,
        },
    }
    return results, vote_matrix_pca_scaled, pca, user_labels


def _compute_stability_metrics(
    vote_matrix_filled,
    vote_matrix_real,
    baseline_labels,
    baseline_consensus,
    baseline_bridge,
    baseline_divisive,
    method,
    base_seed,
    run_count,
):
    """
    Compute cluster and statement stability across repeated seeded runs.

    Used for BOTH full-matrix and oversize analyses so every published
    result carries a reproducibility signal. See Monti et al. (2003) for
    the consensus-clustering motivation.
    """
    runs = max(1, int(run_count))
    if runs <= 1:
        # A single run has no comparison baseline, so report perfect stability
        # (the result is trivially consistent with itself). This avoids the
        # publishability gate defaulting stability_mean_ari to 0.0 and
        # permanently withholding all oversize analyses when STABILITY_RUNS=1.
        return {
            'stability_runs': 1,
            'stability_mean_ari': 1.0,
            'stability_min_ari': 1.0,
            'stability_max_ari': 1.0,
            'stability_consensus_jaccard_mean': 1.0,
            'stability_bridge_jaccard_mean': 1.0,
            'stability_divisive_jaccard_mean': 1.0,
        }

    baseline_consensus_set = _statement_id_set(baseline_consensus)
    baseline_bridge_set = _statement_id_set(baseline_bridge)
    baseline_divisive_set = _statement_id_set(baseline_divisive)

    ari_scores = []
    consensus_jaccards = []
    bridge_jaccards = []
    divisive_jaccards = []

    # PCA + sparsity scaling are deterministic on the same inputs — compute
    # once per stability call, not once per re-seeded clustering run.
    vote_matrix_pca, _ = perform_pca(vote_matrix_filled)
    vote_matrix_pca_scaled = apply_sparsity_scaling(vote_matrix_pca, vote_matrix_real)

    fixed_k = int(len(np.unique(baseline_labels)))
    for run_idx in range(1, runs):
        seed = int(base_seed + run_idx)
        labels, _ = cluster_users(
            vote_matrix_pca_scaled,
            n_clusters=fixed_k,
            method=method,
            random_state=seed,
        )
        ari_scores.append(_adjusted_rand_index(baseline_labels, labels))

        run_consensus = _statement_id_set(identify_consensus_statements(vote_matrix_real, labels))
        run_bridge = _statement_id_set(identify_bridge_statements(vote_matrix_real, labels))
        run_divisive = _statement_id_set(identify_divisive_statements(vote_matrix_real, labels))
        consensus_jaccards.append(_jaccard_similarity(baseline_consensus_set, run_consensus))
        bridge_jaccards.append(_jaccard_similarity(baseline_bridge_set, run_bridge))
        divisive_jaccards.append(_jaccard_similarity(baseline_divisive_set, run_divisive))

    return {
        'stability_runs': int(runs),
        'stability_mean_ari': float(np.mean(ari_scores)) if ari_scores else 1.0,
        'stability_min_ari': float(np.min(ari_scores)) if ari_scores else 1.0,
        'stability_max_ari': float(np.max(ari_scores)) if ari_scores else 1.0,
        'stability_consensus_jaccard_mean': (
            float(np.mean(consensus_jaccards)) if consensus_jaccards else 1.0
        ),
        'stability_bridge_jaccard_mean': (
            float(np.mean(bridge_jaccards)) if bridge_jaccards else 1.0
        ),
        'stability_divisive_jaccard_mean': (
            float(np.mean(divisive_jaccards)) if divisive_jaccards else 1.0
        ),
    }


def run_consensus_analysis(discussion_id, db, method='agglomerative'):
    """
    Main function to run complete consensus analysis on a discussion.

    Always attaches stability metrics (ARI + per-category Jaccard) computed
    over re-seeded repeated runs. The publishability gate in the view
    layer consults these to decide whether a noisy cluster structure
    should be withheld from end users.
    """
    from flask import current_app

    plan = get_consensus_execution_plan(discussion_id, db)
    if not plan['is_ready']:
        logger.warning(f"Cannot cluster discussion {discussion_id}: {plan['message']}")
        return None
    if plan['mode'] != 'full_matrix':
        logger.info(
            f"Running oversize consensus fallback for discussion {discussion_id}: {plan['message']}"
        )
        return build_oversize_consensus_results(discussion_id, db, plan)

    vote_matrix_filled, vote_matrix_real, user_ids, statement_ids = build_vote_matrix(discussion_id, db)
    results, _, _, user_labels = _build_analysis_payload(
        user_ids=user_ids,
        statement_ids=statement_ids,
        vote_matrix_filled=vote_matrix_filled,
        vote_matrix_real=vote_matrix_real,
        method=method,
        random_state=42,
    )
    if results is None:
        return None

    stability_runs = int(
        current_app.config.get('CONSENSUS_FULL_MATRIX_STABILITY_RUNS', 3)
    )
    stability_metrics = _compute_stability_metrics(
        vote_matrix_filled=vote_matrix_filled,
        vote_matrix_real=vote_matrix_real,
        baseline_labels=user_labels,
        baseline_consensus=results['consensus_statements'],
        baseline_bridge=results['bridge_statements'],
        baseline_divisive=results['divisive_statements'],
        method=method,
        base_seed=int(discussion_id),
        run_count=stability_runs,
    )
    results['metadata'].update(stability_metrics)
    results['metadata']['publication_min_stability_mean_ari'] = float(
        current_app.config.get('CONSENSUS_FULL_MATRIX_MIN_STABILITY_ARI', 0.20)
    )

    logger.info(f"Consensus analysis complete for discussion {discussion_id}")
    logger.info(f"  - {len(user_ids)} users in {len(np.unique(user_labels))} clusters")
    logger.info(
        "  - %s consensus, %s bridge, %s divisive",
        len(results['consensus_statements']),
        len(results['bridge_statements']),
        len(results['divisive_statements']),
    )
    logger.info(
        "  - %s representative statements identified",
        sum(len(v) for v in results['representative_statements'].values()),
    )
    logger.info(
        "  - stability mean ARI=%.3f across %d runs",
        stability_metrics.get('stability_mean_ari', 1.0),
        stability_metrics.get('stability_runs', 1),
    )

    return results


def save_consensus_analysis(discussion_id, results, db):
    """
    Save consensus analysis results to database
    """
    from app.models import ConsensusAnalysis, Discussion
    
    analysis = ConsensusAnalysis(
        discussion_id=discussion_id,
        cluster_data=results,  # Stored as JSON
        num_clusters=results['metadata']['num_clusters'],
        silhouette_score=results['metadata']['silhouette_score'],
        method=results['metadata']['method'],
        participants_count=results['metadata']['participants_count'],
        statements_count=results['metadata']['statements_count']
    )
    
    db.session.add(analysis)
    db.session.commit()
    try:
        from app.api.utils import invalidate_partner_snapshot_cache
        invalidate_partner_snapshot_cache(discussion_id)
    except Exception:
        pass

    try:
        discussion = db.session.get(Discussion, discussion_id)
        if discussion and discussion.partner_fk_id:
            from app.partner.webhooks import emit_partner_event
            from app.partner.events import EVENT_CONSENSUS_UPDATED, serialize_consensus_payload
            emit_partner_event(
                partner_id=discussion.partner_fk_id,
                event_type=EVENT_CONSENSUS_UPDATED,
                data=serialize_consensus_payload(discussion, analysis),
            )
    except Exception:
        logger.exception("Failed to emit consensus.updated webhook event for discussion %s", discussion_id)
    
    logger.info(f"Saved consensus analysis for discussion {discussion_id}")
    return analysis

