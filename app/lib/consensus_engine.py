# app/lib/consensus_engine.py
"""
Consensus Clustering Engine (Phase 3)

Vote-based user clustering inspired by pol.is
Uses PCA + Agglomerative Clustering to find opinion groups
Identifies consensus, bridge, and divisive statements

Based on pol.is clustering patterns (AGPL-3.0)

RECENT IMPROVEMENTS (2026-01-05):
- Changed missing vote fill strategy from 0 (neutral) to statement mean
  This preserves vote distribution and improves clustering accuracy
- Removed StandardScaler before PCA to preserve meaningful variance signals
  Variance = consensus vs division, which is exactly what PCA should focus on

RECENT IMPROVEMENTS (2026-01-06):
- Added SparsityAwareScaler after PCA (pol.is innovation)
  Prevents sparse voters from bunching at center, enables 4-5+ opinion groups
  Code adapted from pol.is red-dwarf library: https://github.com/polis-community/red-dwarf
"""
import numpy as np
import pandas as pd
from datetime import datetime
from app.lib.time import utcnow_naive
from typing import Dict, List, Tuple, Optional
import logging

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
    - At least 7 participants (users + anonymous)
    - At least 7 statements
    - At least 50 total votes
    - Each statement has at least 3 votes
    """
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
    
    # Check minimum votes per statement (only non-deleted statements)
    min_votes_per_statement = db.session.query(
        StatementVote.statement_id,
        db.func.count(StatementVote.id).label('vote_count')
    ).join(Statement, StatementVote.statement_id == Statement.id).filter(
        StatementVote.discussion_id == discussion_id,
        Statement.is_deleted.is_(False)
    ).group_by(StatementVote.statement_id).all()
    
    if not min_votes_per_statement:
        return False, "No votes yet"
    
    min_votes = min([v[1] for v in min_votes_per_statement])
    
    # Apply criteria
    if participant_count < 7:
        return False, f"Need at least 7 participants (have {participant_count})"
    if statement_count < 7:
        return False, f"Need at least 7 statements (have {statement_count})"
    if vote_count < 50:
        return False, f"Need at least 50 votes (have {vote_count})"
    if min_votes < 3:
        return False, f"Some statements have fewer than 3 votes"
    
    return True, "Ready for clustering"


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
    try:
        from sklearn.decomposition import PCA

        pca = PCA(n_components=n_components)
        vote_matrix_pca = pca.fit_transform(vote_matrix)

        logger.info(f"PCA explained variance: {pca.explained_variance_ratio_}")
        logger.info(f"PCA components shape: {vote_matrix_pca.shape}")

        return vote_matrix_pca, pca
    except (OSError, ImportError) as e:
        logger.error(f"sklearn PCA import failed ({e}), using numpy fallback")
        matrix = np.array(vote_matrix)
        transformed, explained_ratios = _numpy_pca(matrix, n_components)

        # Return a lightweight object with the attribute the caller needs
        class _PCAResult:
            def __init__(self, ratios):
                self.explained_variance_ratio_ = ratios

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


def cluster_users(vote_matrix_pca, n_clusters=None, method='agglomerative'):
    """
    Cluster users based on PCA-reduced vote matrix

    Pol.is uses agglomerative clustering with automatic k selection
    We'll use silhouette score to find optimal k
    """
    try:
        from sklearn.cluster import AgglomerativeClustering, KMeans
        from sklearn.metrics import silhouette_score
        _use_sklearn = True
    except (OSError, ImportError) as e:
        logger.error(f"sklearn clustering import failed ({e}), using numpy fallback")
        _use_sklearn = False

    if n_clusters is None:
        # Find optimal number of clusters (2 to min(10, n_users/2))
        max_clusters = min(10, len(vote_matrix_pca) // 2)

        if max_clusters < 2:
            logger.warning("Not enough users for clustering")
            return np.zeros(len(vote_matrix_pca)), 0

        best_score = -1
        best_k = 2

        for k in range(2, max_clusters + 1):
            if _use_sklearn:
                try:
                    if method == 'agglomerative':
                        clusterer = AgglomerativeClustering(
                            n_clusters=k,
                            linkage='average',
                            metric='cosine'
                        )
                    else:
                        clusterer = KMeans(n_clusters=k, random_state=42)
                    labels = clusterer.fit_predict(vote_matrix_pca)
                    score = silhouette_score(vote_matrix_pca, labels, metric='cosine')
                except (OSError, ImportError) as e:
                    logger.error(
                        f"sklearn clustering runtime failed ({e}), switching to numpy fallback"
                    )
                    _use_sklearn = False
                    labels = _numpy_agglomerative(np.array(vote_matrix_pca), k)
                    score = _numpy_silhouette(np.array(vote_matrix_pca), labels)
            else:
                labels = _numpy_agglomerative(np.array(vote_matrix_pca), k)
                score = _numpy_silhouette(np.array(vote_matrix_pca), labels)

            logger.info(f"k={k}: silhouette={score:.3f}")

            if score > best_score:
                best_score = score
                best_k = k

        n_clusters = best_k
        logger.info(f"Selected {n_clusters} clusters (silhouette={best_score:.3f})")

    # Final clustering with optimal k
    if _use_sklearn:
        try:
            if method == 'agglomerative':
                clusterer = AgglomerativeClustering(
                    n_clusters=n_clusters,
                    linkage='average',
                    metric='cosine'
                )
            else:
                clusterer = KMeans(n_clusters=n_clusters, random_state=42)
            labels = clusterer.fit_predict(vote_matrix_pca)
            silhouette = silhouette_score(vote_matrix_pca, labels, metric='cosine')
        except (OSError, ImportError) as e:
            logger.error(
                f"sklearn final clustering runtime failed ({e}), using numpy fallback"
            )
            labels = _numpy_agglomerative(np.array(vote_matrix_pca), n_clusters)
            silhouette = _numpy_silhouette(np.array(vote_matrix_pca), labels)
    else:
        labels = _numpy_agglomerative(np.array(vote_matrix_pca), n_clusters)
        silhouette = _numpy_silhouette(np.array(vote_matrix_pca), labels)

    return labels, silhouette


def identify_consensus_statements(vote_matrix, user_labels, consensus_threshold=0.7, cluster_threshold=0.6):
    """
    Identify statements with broad consensus

    Pol.is criteria:
    - ≥70% overall agreement
    - ≥60% agreement in EACH cluster

    Note: Uses real votes only (NaN = no vote), not imputed values

    Returns:
        List of (statement_id, agreement_rate) tuples
    """
    consensus_statements = []

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]

        # Calculate overall agreement (agree votes / total REAL votes)
        # Only count actual votes, not NaN (missing votes)
        real_votes = statement_votes.notna()
        agree_votes = (statement_votes == 1).sum()
        total_votes = real_votes.sum()

        if total_votes == 0:
            continue

        overall_agreement = agree_votes / total_votes

        if overall_agreement < consensus_threshold:
            continue

        # Check agreement in each cluster (Pol.is: every cluster must have voted and meet threshold)
        n_clusters = len(np.unique(user_labels))
        cluster_agreements = []
        for cluster_id in np.unique(user_labels):
            cluster_mask = user_labels == cluster_id
            cluster_votes = statement_votes[vote_matrix.index[cluster_mask]]

            cluster_real = cluster_votes.notna()
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = cluster_real.sum()

            if cluster_total > 0:
                cluster_agreement = cluster_agree / cluster_total
                cluster_agreements.append(cluster_agreement)

        # All clusters must have at least one vote AND meet threshold (no "consensus" if a group didn't vote)
        if len(cluster_agreements) == n_clusters and all(ca >= cluster_threshold for ca in cluster_agreements):
            consensus_statements.append({
                'statement_id': statement_id,
                'agreement_rate': overall_agreement,
                'cluster_agreements': cluster_agreements
            })

    logger.info(f"Found {len(consensus_statements)} consensus statements")
    return consensus_statements


def identify_bridge_statements(vote_matrix, user_labels, min_agreement=0.65, max_variance=0.15):
    """
    Identify bridge statements that unite different clusters

    Pol.is criteria:
    - High mean agreement across clusters (≥65%)
    - Low variance across clusters (<0.15)

    Note: Uses real votes only (NaN = no vote), not imputed values

    Returns:
        List of (statement_id, mean_agreement, variance) tuples
    """
    bridge_statements = []

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]

        # Calculate agreement in each cluster (using real votes only; all clusters must have voted)
        n_clusters = len(np.unique(user_labels))
        cluster_agreements = []
        for cluster_id in np.unique(user_labels):
            cluster_mask = user_labels == cluster_id
            cluster_votes = statement_votes[vote_matrix.index[cluster_mask]]

            cluster_real = cluster_votes.notna()
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = cluster_real.sum()

            if cluster_total > 0:
                cluster_agreement = cluster_agree / cluster_total
                cluster_agreements.append(cluster_agreement)

        if len(cluster_agreements) < 2 or len(cluster_agreements) != n_clusters:
            continue

        mean_agreement = np.mean(cluster_agreements)
        variance = np.var(cluster_agreements)

        if mean_agreement >= min_agreement and variance <= max_variance:
            bridge_statements.append({
                'statement_id': statement_id,
                'mean_agreement': mean_agreement,
                'variance': variance,
                'cluster_agreements': cluster_agreements
            })

    logger.info(f"Found {len(bridge_statements)} bridge statements")
    return bridge_statements


def identify_divisive_statements(vote_matrix, user_labels, min_controversy=0.7):
    """
    Identify divisive statements with strong disagreement

    High controversy score (close to 50/50 split)

    Note: Uses real votes only (NaN = no vote), not imputed values
    Only counts agree/disagree votes (not unsure)

    Returns:
        List of (statement_id, controversy_score) tuples
    """
    divisive_statements = []

    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]

        # Only count explicit agree/disagree (NaN won't match, so excluded automatically)
        agree_votes = (statement_votes == 1).sum()
        disagree_votes = (statement_votes == -1).sum()
        total_votes = agree_votes + disagree_votes

        if total_votes < 5:  # Need enough votes
            continue

        agree_rate = agree_votes / total_votes if total_votes > 0 else 0

        # Controversy score: 1 - |agree_rate - 0.5| * 2
        # Peaks at 1.0 when agree_rate = 0.5 (50/50 split)
        controversy = 1 - abs(agree_rate - 0.5) * 2

        if controversy >= min_controversy:
            divisive_statements.append({
                'statement_id': statement_id,
                'controversy_score': controversy,
                'agree_rate': agree_rate
            })

    logger.info(f"Found {len(divisive_statements)} divisive statements")
    return divisive_statements


def identify_representative_statements(vote_matrix, user_labels, top_n=5):
    """
    Identify the most representative statements for each opinion group.

    Representative statements are those with high agreement within each group.
    This makes opinion groups interpretable: "Group 1 believes [X, Y, Z]"

    This is inspired by pol.is's approach to characterizing opinion groups
    and makes clustering results actionable for users.

    Args:
        vote_matrix: DataFrame with real votes (NaN for missing)
        user_labels: Cluster assignments for each participant
        top_n: Number of top statements to return per group (default 5)

    Returns:
        Dict mapping cluster_id -> list of representative statements
        Each statement includes: statement_id, agreement_rate, vote_count, strength
    """
    representatives = {}

    for cluster_id in np.unique(user_labels):
        cluster_mask = user_labels == cluster_id
        cluster_indices = np.where(cluster_mask)[0]
        cluster_votes = vote_matrix.iloc[cluster_indices]

        # Calculate agreement for each statement within this cluster
        statement_scores = []
        for statement_id in cluster_votes.columns:
            votes = cluster_votes[statement_id]
            real_votes = votes.notna()
            vote_count = real_votes.sum()

            if vote_count < 3:  # Need minimum votes to be representative
                continue

            # Calculate agreement rate (% who agree among those who voted)
            agree_count = (votes == 1).sum()
            agreement_rate = agree_count / vote_count

            # Calculate "strength" - high agreement weighted by participation
            # This ensures we pick statements that are both agreed upon AND voted on
            # Participation weight caps at 1.0 (if everyone in cluster voted)
            participation_weight = min(vote_count / len(cluster_votes), 1.0)
            strength = agreement_rate * participation_weight

            statement_scores.append({
                'statement_id': int(statement_id),
                'agreement_rate': float(agreement_rate),
                'vote_count': int(vote_count),
                'agree_count': int(agree_count),
                'strength': float(strength)
            })

        # Sort by strength (agreement weighted by participation)
        statement_scores.sort(key=lambda x: x['strength'], reverse=True)

        # Take top N
        representatives[int(cluster_id)] = statement_scores[:top_n]

    logger.info(f"Identified {sum(len(v) for v in representatives.values())} representative statements across {len(representatives)} groups")

    return representatives


def run_consensus_analysis(discussion_id, db, method='agglomerative'):
    """
    Main function to run complete consensus analysis on a discussion

    Returns:
        Dictionary with:
        - cluster_assignments: user_id -> cluster_id mapping
        - pca_coordinates: user_id -> (x, y) coordinates
        - consensus_statements: list of consensus statement details
        - bridge_statements: list of bridge statement details
        - divisive_statements: list of divisive statement details
        - representative_statements: dict of cluster_id -> top statements that group agrees on
        - metadata: clustering metadata (n_clusters, silhouette_score, etc.)
    """
    # Check if ready for clustering
    ready, message = can_cluster(discussion_id, db)
    if not ready:
        logger.warning(f"Cannot cluster discussion {discussion_id}: {message}")
        return None
    
    # Build vote matrices (filled for PCA, real for consensus metrics)
    vote_matrix_filled, vote_matrix_real, user_ids, statement_ids = build_vote_matrix(discussion_id, db)

    if vote_matrix_filled is None or len(user_ids) == 0:
        return None

    # Perform PCA on filled matrix (imputed values help PCA see patterns)
    vote_matrix_pca, pca = perform_pca(vote_matrix_filled)

    # Apply sparsity-aware scaling (pol.is innovation)
    # This prevents sparse voters from bunching at center, enabling 4-5+ clusters
    vote_matrix_pca_scaled = apply_sparsity_scaling(vote_matrix_pca, vote_matrix_real)

    # Cluster users based on scaled PCA coordinates
    user_labels, silhouette = cluster_users(vote_matrix_pca_scaled, method=method)

    # Create user-cluster mapping
    # user_ids are strings like "u_42" (authenticated) or "a_abc123" (anonymous)
    cluster_assignments = {
        user_id: int(label)
        for user_id, label in zip(user_ids, user_labels)
    }

    # Create PCA coordinates mapping (using scaled coordinates for visualization)
    pca_coordinates = {
        user_id: (float(coords[0]), float(coords[1]))
        for user_id, coords in zip(user_ids, vote_matrix_pca_scaled)
    }

    # Identify special statements using REAL votes only (not imputed)
    # This ensures consensus metrics only count actual participant votes
    consensus_stmts = identify_consensus_statements(vote_matrix_real, user_labels)
    bridge_stmts = identify_bridge_statements(vote_matrix_real, user_labels)
    divisive_stmts = identify_divisive_statements(vote_matrix_real, user_labels)

    # Identify representative statements for each opinion group
    # This helps users understand "what does each group believe?"
    representative_stmts = identify_representative_statements(vote_matrix_real, user_labels)

    # Compile results
    results = {
        'cluster_assignments': cluster_assignments,
        'pca_coordinates': pca_coordinates,
        'consensus_statements': consensus_stmts,
        'bridge_statements': bridge_stmts,
        'divisive_statements': divisive_stmts,
        'representative_statements': representative_stmts,
        'metadata': {
            'num_clusters': int(len(np.unique(user_labels))),
            'silhouette_score': float(silhouette),
            'method': method,
            'participants_count': len(user_ids),
            'statements_count': len(statement_ids),
            'analyzed_at': utcnow_naive().isoformat(),
            'explained_variance': pca.explained_variance_ratio_.tolist()
        }
    }
    
    logger.info(f"Consensus analysis complete for discussion {discussion_id}")
    logger.info(f"  - {len(user_ids)} users in {len(np.unique(user_labels))} clusters")
    logger.info(f"  - {len(consensus_stmts)} consensus, {len(bridge_stmts)} bridge, {len(divisive_stmts)} divisive")
    logger.info(f"  - {sum(len(v) for v in representative_stmts.values())} representative statements identified")

    return results


def save_consensus_analysis(discussion_id, results, db):
    """
    Save consensus analysis results to database
    """
    from app.models import ConsensusAnalysis
    
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
    
    logger.info(f"Saved consensus analysis for discussion {discussion_id}")
    return analysis

