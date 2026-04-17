"""Guided journey analytics helpers."""
from app.programmes.journey_analytics import compute_topic_rankings


def test_compute_topic_rankings_empty_db(app, db):
    """Smoke test: no crash on empty or sparse data."""
    with app.app_context():
        rows = compute_topic_rankings(limit=5)
        assert isinstance(rows, list)
