def test_save_consensus_analysis_invalidates_partner_snapshot_cache(app, db):
    from app import cache
    from app.models import Discussion
    from app.lib.consensus_engine import save_consensus_analysis

    discussion = Discussion(
        title='Cache Invalidation Discussion',
        slug='cache-invalidation-discussion',
        has_native_statements=True,
        geographic_scope='global',
        partner_env='live',
    )
    db.session.add(discussion)
    db.session.commit()

    cache_key = f"snapshot:{discussion.id}"
    cache.set(cache_key, {'stale': True}, timeout=600)
    assert cache.get(cache_key) is not None

    results = {
        'cluster_assignments': {},
        'pca_coordinates': {},
        'consensus_statements': [],
        'bridge_statements': [],
        'divisive_statements': [],
        'representative_statements': {},
        'metadata': {
            'num_clusters': 0,
            'silhouette_score': 0.0,
            'method': 'agglomerative',
            'participants_count': 0,
            'statements_count': 0,
            'analyzed_at': '2026-01-01T00:00:00',
            'explained_variance': [],
        },
    }

    save_consensus_analysis(discussion.id, results, db)

    assert cache.get(cache_key) is None
