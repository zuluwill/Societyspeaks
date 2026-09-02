"""The discussion statement list must not load every argument just to count them.

The card only shows a badge. Loading ``Statement.responses`` (and each
Response.user) for a page of 20 statements is how the core read path grew
with every reply written — a count that SQL can answer in one grouped query.
"""

from datetime import timedelta
from pathlib import Path

from flask import url_for
from sqlalchemy import event

from app.lib.time import utcnow_naive
from app.models import generate_slug


ROOT = Path(__file__).resolve().parents[1]
ROUTES = ROOT / 'app/discussions/routes.py'
CARD = ROOT / 'app/templates/discussions/_statement_card.html'


def test_list_query_does_not_eager_load_response_bodies():
    source = ROUTES.read_text(encoding='utf-8')
    assert 'selectinload(Statement.responses)' not in source
    assert '_annotate_visible_response_counts(' in source


def test_statement_card_uses_the_precomputed_count():
    source = CARD.read_text(encoding='utf-8')
    assert 'statement._visible_response_count' in source
    assert "statement.responses|rejectattr('is_deleted')" not in source


def _discussion_with_statements(db):
    from app.models import Discussion, Response, Statement

    discussion = Discussion(
        title='List query discussion',
        slug=generate_slug('List query discussion'),
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()

    now = utcnow_naive()
    first = Statement(
        discussion_id=discussion.id,
        content='First claim that is long enough',
        created_at=now - timedelta(hours=2),
        is_deleted=False,
        mod_status=0,
    )
    second = Statement(
        discussion_id=discussion.id,
        content='Second claim that is long enough',
        created_at=now - timedelta(hours=1),
        is_deleted=False,
        mod_status=0,
    )
    db.session.add_all([first, second])
    db.session.flush()

    db.session.add_all([
        Response(statement_id=first.id, content='Visible argument one',
                 is_deleted=False, position='pro'),
        Response(statement_id=first.id, content='Visible argument two',
                 is_deleted=False, position='con'),
        Response(statement_id=first.id, content='Deleted argument body',
                 is_deleted=True, position='pro'),
        Response(statement_id=second.id, content='Only visible argument',
                 is_deleted=False, position='pro'),
    ])
    db.session.commit()
    return discussion, first, second


def _count_response_body_selects(db):
    seen = []

    def _record(conn, cursor, statement, params, context, executemany):
        sql = ' '.join(statement.lower().split())
        if ' from response' not in sql:
            return
        # A COUNT/group-by to populate the badge is expected. Selecting
        # response rows (content, user_id, ...) is the regression.
        if 'count(' in sql:
            return
        seen.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _record)
    return seen, lambda: event.remove(db.engine, 'before_cursor_execute', _record)


def test_discussion_page_counts_responses_without_loading_bodies(app, db, client):
    discussion, first, second = _discussion_with_statements(db)

    with app.test_request_context():
        url = url_for(
            'discussions.view_discussion',
            discussion_id=discussion.id,
            slug=discussion.slug,
        )

    seen, stop = _count_response_body_selects(db)
    try:
        response = client.get(url)
    finally:
        stop()

    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert 'Visible argument one' not in body
    assert 'Deleted argument body' not in body
    assert seen == [], (
        'discussion page loaded response rows instead of counting them:\n'
        + '\n'.join(seen)
    )
    # Two visible replies on the first statement, one on the second.
    first_card = body[body.index(first.content):]
    assert '>2</span>' in first_card.split(second.content, 1)[0]
    assert '2 responses so far' in first_card.split(second.content, 1)[0]
    assert '1 response so far' in body[body.index(second.content):]


def test_statement_list_api_uses_the_same_count(app, db, client):
    discussion, first, _second = _discussion_with_statements(db)

    with app.test_request_context():
        url = url_for(
            'discussions.api_discussion_statements',
            discussion_id=discussion.id,
        )

    seen, stop = _count_response_body_selects(db)
    try:
        response = client.get(url)
    finally:
        stop()

    assert response.status_code == 200
    payload = response.get_json()
    assert payload['success'] is True
    assert seen == []
    assert first.content in payload['html']
    assert '2 responses so far' in payload['html']
    assert 'Visible argument one' not in payload['html']
