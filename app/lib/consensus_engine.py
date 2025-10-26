# app/lib/consensus_engine.py
"""
Consensus Clustering Engine (Phase 3)

Vote-based user clustering inspired by pol.is
Uses PCA + Agglomerative Clustering to find opinion groups
Identifies consensus, bridge, and divisive statements

Based on pol.is clustering patterns (AGPL-3.0)
"""
import numpy as np
import pandas as pd
from datetime import datetime
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


def build_vote_matrix(discussion_id, db):
    """
    Build vote matrix from statement votes
    Rows = users, Columns = statements, Values = votes (-1, 0, 1)
    
    Returns:
        vote_matrix: pandas DataFrame (users x statements)
        user_ids: list of user IDs
        statement_ids: list of statement IDs
    """
    from app.models import StatementVote, Statement
    
    # Get all votes for this discussion
    votes = db.session.query(
        StatementVote.user_id,
        StatementVote.statement_id,
        StatementVote.vote
    ).filter(
        StatementVote.discussion_id == discussion_id
    ).all()
    
    if not votes:
        return None, [], []
    
    # Convert to DataFrame
    df = pd.DataFrame(votes, columns=['user_id', 'statement_id', 'vote'])
    
    # Pivot to create matrix
    vote_matrix = df.pivot_table(
        index='user_id',
        columns='statement_id',
        values='vote',
        fill_value=0  # Users who haven't voted get 0 (neutral)
    )
    
    user_ids = vote_matrix.index.tolist()
    statement_ids = vote_matrix.columns.tolist()
    
    logger.info(f"Built vote matrix: {len(user_ids)} users x {len(statement_ids)} statements")
    
    return vote_matrix, user_ids, statement_ids


def can_cluster(discussion_id, db):
    """
    Check if discussion has enough data for meaningful clustering
    
    Criteria (from pol.is analysis):
    - At least 7 users
    - At least 7 statements
    - At least 50 total votes
    - Each statement has at least 3 votes
    """
    from app.models import StatementVote, Statement
    
    # Count unique users
    user_count = db.session.query(StatementVote.user_id).filter(
        StatementVote.discussion_id == discussion_id
    ).distinct().count()
    
    # Count statements
    statement_count = Statement.query.filter_by(
        discussion_id=discussion_id,
        is_deleted=False
    ).count()
    
    # Count total votes
    vote_count = StatementVote.query.filter(
        StatementVote.discussion_id == discussion_id
    ).count()
    
    # Check minimum votes per statement
    min_votes_per_statement = db.session.query(
        StatementVote.statement_id,
        db.func.count(StatementVote.id).label('vote_count')
    ).filter(
        StatementVote.discussion_id == discussion_id
    ).group_by(StatementVote.statement_id).all()
    
    if not min_votes_per_statement:
        return False, "No votes yet"
    
    min_votes = min([v[1] for v in min_votes_per_statement])
    
    # Apply criteria
    if user_count < 7:
        return False, f"Need at least 7 users (have {user_count})"
    if statement_count < 7:
        return False, f"Need at least 7 statements (have {statement_count})"
    if vote_count < 50:
        return False, f"Need at least 50 votes (have {vote_count})"
    if min_votes < 3:
        return False, f"Some statements have fewer than 3 votes"
    
    return True, "Ready for clustering"


def perform_pca(vote_matrix, n_components=2):
    """
    Perform PCA dimensionality reduction
    Pol.is uses 2 components for visualization
    """
    from sklearn.decomposition import PCA
    
    # Standardize the data
    from sklearn.preprocessing import StandardScaler
    scaler = StandardScaler()
    vote_matrix_scaled = scaler.fit_transform(vote_matrix)
    
    # Apply PCA
    pca = PCA(n_components=n_components)
    vote_matrix_pca = pca.fit_transform(vote_matrix_scaled)
    
    logger.info(f"PCA explained variance: {pca.explained_variance_ratio_}")
    
    return vote_matrix_pca, pca


def cluster_users(vote_matrix_pca, n_clusters=None, method='agglomerative'):
    """
    Cluster users based on PCA-reduced vote matrix
    
    Pol.is uses agglomerative clustering with automatic k selection
    We'll use silhouette score to find optimal k
    """
    from sklearn.cluster import AgglomerativeClustering, KMeans
    from sklearn.metrics import silhouette_score
    
    if n_clusters is None:
        # Find optimal number of clusters (2 to min(10, n_users/2))
        max_clusters = min(10, len(vote_matrix_pca) // 2)
        
        if max_clusters < 2:
            logger.warning("Not enough users for clustering")
            return np.zeros(len(vote_matrix_pca)), 0
        
        best_score = -1
        best_k = 2
        
        for k in range(2, max_clusters + 1):
            if method == 'agglomerative':
                clusterer = AgglomerativeClustering(
                    n_clusters=k,
                    linkage='average',
                    metric='cosine'
                )
            else:  # kmeans
                clusterer = KMeans(n_clusters=k, random_state=42)
            
            labels = clusterer.fit_predict(vote_matrix_pca)
            score = silhouette_score(vote_matrix_pca, labels, metric='cosine')
            
            logger.info(f"k={k}: silhouette={score:.3f}")
            
            if score > best_score:
                best_score = score
                best_k = k
        
        n_clusters = best_k
        logger.info(f"Selected {n_clusters} clusters (silhouette={best_score:.3f})")
    
    # Final clustering with optimal k
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
    
    return labels, silhouette


def identify_consensus_statements(vote_matrix, user_labels, consensus_threshold=0.7, cluster_threshold=0.6):
    """
    Identify statements with broad consensus
    
    Pol.is criteria:
    - ≥70% overall agreement
    - ≥60% agreement in EACH cluster
    
    Returns:
        List of (statement_id, agreement_rate) tuples
    """
    consensus_statements = []
    
    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]
        
        # Calculate overall agreement (agree votes / total votes)
        agree_votes = (statement_votes == 1).sum()
        total_votes = (statement_votes != 0).sum()
        
        if total_votes == 0:
            continue
        
        overall_agreement = agree_votes / total_votes
        
        if overall_agreement < consensus_threshold:
            continue
        
        # Check agreement in each cluster
        cluster_agreements = []
        for cluster_id in np.unique(user_labels):
            cluster_mask = user_labels == cluster_id
            cluster_votes = statement_votes[vote_matrix.index[cluster_mask]]
            
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = (cluster_votes != 0).sum()
            
            if cluster_total > 0:
                cluster_agreement = cluster_agree / cluster_total
                cluster_agreements.append(cluster_agreement)
        
        # All clusters must meet threshold
        if all(ca >= cluster_threshold for ca in cluster_agreements):
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
    
    Returns:
        List of (statement_id, mean_agreement, variance) tuples
    """
    bridge_statements = []
    
    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]
        
        # Calculate agreement in each cluster
        cluster_agreements = []
        for cluster_id in np.unique(user_labels):
            cluster_mask = user_labels == cluster_id
            cluster_votes = statement_votes[vote_matrix.index[cluster_mask]]
            
            cluster_agree = (cluster_votes == 1).sum()
            cluster_total = (cluster_votes != 0).sum()
            
            if cluster_total > 0:
                cluster_agreement = cluster_agree / cluster_total
                cluster_agreements.append(cluster_agreement)
        
        if len(cluster_agreements) < 2:
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
    
    Returns:
        List of (statement_id, controversy_score) tuples
    """
    divisive_statements = []
    
    for statement_id in vote_matrix.columns:
        statement_votes = vote_matrix[statement_id]
        
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
        - metadata: clustering metadata (n_clusters, silhouette_score, etc.)
    """
    # Check if ready for clustering
    ready, message = can_cluster(discussion_id, db)
    if not ready:
        logger.warning(f"Cannot cluster discussion {discussion_id}: {message}")
        return None
    
    # Build vote matrix
    vote_matrix, user_ids, statement_ids = build_vote_matrix(discussion_id, db)
    
    if vote_matrix is None or len(user_ids) == 0:
        return None
    
    # Perform PCA
    vote_matrix_pca, pca = perform_pca(vote_matrix)
    
    # Cluster users
    user_labels, silhouette = cluster_users(vote_matrix_pca, method=method)
    
    # Create user-cluster mapping
    cluster_assignments = {
        int(user_id): int(label)
        for user_id, label in zip(user_ids, user_labels)
    }
    
    # Create PCA coordinates mapping
    pca_coordinates = {
        int(user_id): (float(coords[0]), float(coords[1]))
        for user_id, coords in zip(user_ids, vote_matrix_pca)
    }
    
    # Identify special statements
    consensus_stmts = identify_consensus_statements(vote_matrix, user_labels)
    bridge_stmts = identify_bridge_statements(vote_matrix, user_labels)
    divisive_stmts = identify_divisive_statements(vote_matrix, user_labels)
    
    # Compile results
    results = {
        'cluster_assignments': cluster_assignments,
        'pca_coordinates': pca_coordinates,
        'consensus_statements': consensus_stmts,
        'bridge_statements': bridge_stmts,
        'divisive_statements': divisive_stmts,
        'metadata': {
            'num_clusters': int(len(np.unique(user_labels))),
            'silhouette_score': float(silhouette),
            'method': method,
            'participants_count': len(user_ids),
            'statements_count': len(statement_ids),
            'analyzed_at': datetime.utcnow().isoformat(),
            'explained_variance': pca.explained_variance_ratio_.tolist()
        }
    }
    
    logger.info(f"Consensus analysis complete for discussion {discussion_id}")
    logger.info(f"  - {len(user_ids)} users in {len(np.unique(user_labels))} clusters")
    logger.info(f"  - {len(consensus_stmts)} consensus, {len(bridge_stmts)} bridge, {len(divisive_stmts)} divisive")
    
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
    
    logger.info(f"Saved consensus analysis for discussion {discussion_id}")
    return analysis

