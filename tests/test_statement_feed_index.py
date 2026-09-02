"""The cross-discussion statement feed must not sort the whole table.

/statements/search lists statements across all discussions ordered by
created_at DESC. Every other "recent" index on statement is prefixed by
discussion_id, so none could serve a query with no discussion filter.

Measured on production (71,973 statements) before idx_statement_recent_global:

    Parallel Seq Scan on statement -> Hash Join -> top-N heapsort
    3,714 buffers, 68.7 ms warm (200 ms mean / 852 ms max in
    pg_stat_statements) to return 20 rows

after:

    Index Scan Backward using idx_statement_recent_global -> Nested Loop
    10 buffers, 0.12 ms
"""

from datetime import timedelta

from flask import url_for

from app.lib.time import utcnow_naive
from app.models import generate_slug


INDEX_NAME = 'idx_statement_recent_global'


def test_model_declares_the_global_recent_index():
    from app.models import Statement

    indexes = {
        idx.name: [c.name for c in idx.columns]
        for idx in Statement.__table__.indexes
    }
    assert INDEX_NAME in indexes, (
        "the cross-discussion feed has no index to order by; it will seq-scan "
        "and top-N sort every statement"
    )
    assert indexes[INDEX_NAME] == ['created_at', 'id'], (
        "index columns must match ORDER BY created_at DESC, id DESC — Postgres "
        "reads an ascending index backwards for this"
    )


def test_existing_per_discussion_indexes_cannot_serve_the_global_feed():
    """Documents why a new index was needed rather than reusing one."""
    from app.models import Statement

    for idx in Statement.__table__.indexes:
        if idx.name == INDEX_NAME:
            continue
        cols = [c.name for c in idx.columns]
        if 'created_at' in cols:
            assert cols[0] == 'discussion_id', (
                f"{idx.name} unexpectedly leads with {cols[0]}; if a non-prefixed "
                f"recent index now exists, {INDEX_NAME} may be redundant"
            )


def test_migration_matches_the_model():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    migration = root / 'migrations/versions/s7n3d5f8h2k4_add_statement_recent_global_index.py'
    source = migration.read_text(encoding='utf-8')

    assert INDEX_NAME in source
    assert "['created_at', 'id']" in source
    assert "down_revision = 'm4k7t2p9q1r3'" in source


def _discussion(db, title):
    from app.models import Discussion

    discussion = Discussion(
        title=title,
        slug=generate_slug(title),
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()
    return discussion


def test_search_returns_statements_newest_first_across_discussions(app, db, client):
    """Behaviour guard: the index must not change what the page shows."""
    from app.models import Statement

    now = utcnow_naive()
    first = _discussion(db, 'Feed Discussion One')
    second = _discussion(db, 'Feed Discussion Two')

    db.session.add_all([
        Statement(discussion_id=first.id, content='Oldest statement here',
                  created_at=now - timedelta(hours=3), is_deleted=False, mod_status=0),
        Statement(discussion_id=second.id, content='Middle statement here',
                  created_at=now - timedelta(hours=2), is_deleted=False, mod_status=0),
        Statement(discussion_id=first.id, content='Newest statement here',
                  created_at=now - timedelta(hours=1), is_deleted=False, mod_status=0),
    ])
    db.session.commit()

    with app.test_request_context():
        url = url_for('discussions.search_statements')

    response = client.get(url)
    assert response.status_code == 200
    body = response.get_data(as_text=True)

    positions = [
        body.index('Newest statement here'),
        body.index('Middle statement here'),
        body.index('Oldest statement here'),
    ]
    assert positions == sorted(positions), "feed must be ordered newest first"


def test_search_excludes_deleted_and_moderated_statements(app, db, client):
    from app.models import Statement

    now = utcnow_naive()
    discussion = _discussion(db, 'Feed Visibility Discussion')
    db.session.add_all([
        Statement(discussion_id=discussion.id, content='Visible statement text',
                  created_at=now, is_deleted=False, mod_status=0),
        Statement(discussion_id=discussion.id, content='Deleted statement text',
                  created_at=now, is_deleted=True, mod_status=0),
        Statement(discussion_id=discussion.id, content='Moderated statement text',
                  created_at=now, is_deleted=False, mod_status=-1),
    ])
    db.session.commit()

    with app.test_request_context():
        url = url_for('discussions.search_statements')
    body = client.get(url).get_data(as_text=True)
    assert 'Visible statement text' in body
    assert 'Deleted statement text' not in body
    assert 'Moderated statement text' not in body
