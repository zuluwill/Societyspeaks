"""DailyBrief must fetch its items once per render, not once per question asked.

``DailyBrief.items`` is lazy='dynamic', which re-queries on every access and
never caches. Four read paths each pulled the whole list, and the brief email
template asks ``brief.is_sectioned`` from inside its per-item loop — so one
11-item brief issued dozens of identical SELECTs.

Production, before the fix (pg_stat_statements, 16-day window):

    calls      rows        rows_per_call
    2,961,670  32,989,912  11.1
    SELECT ... FROM brief_item WHERE $1 = brief_id ORDER BY position

rows_per_call ~= the whole collection is the tell: this was the same list
fetched over and over, not one-row-per-item lookups.
"""

from datetime import date

from sqlalchemy import event


def _count_brief_item_queries(db):
    """Context-manager-ish helper returning a list that collects SQL."""
    seen = []

    def _record(conn, cursor, statement, params, context, executemany):
        if 'brief_item' in statement.lower():
            seen.append(statement)

    event.listen(db.engine, 'before_cursor_execute', _record)
    return seen, lambda: event.remove(db.engine, 'before_cursor_execute', _record)


def _make_brief(db, item_count=5, brief_date=None):
    from app.models import DailyBrief, BriefItem

    brief = DailyBrief(
        date=brief_date or date(2026, 9, 2),
        title='Test Brief',
        status='published',
        brief_type='daily',
    )
    db.session.add(brief)
    db.session.flush()

    for i in range(item_count):
        db.session.add(BriefItem(
            brief_id=brief.id,
            position=i + 1,
            headline=f'Headline {i}',
            section='lead' if i == 0 else 'world',
        ))
    db.session.commit()
    return brief


def test_repeated_property_access_hits_the_database_once(db):
    """The regression. Four properties, many reads, one SELECT."""
    _make_brief(db, item_count=5)
    db.session.expunge_all()

    from app.models import DailyBrief
    loaded = DailyBrief.query.one()

    seen, stop = _count_brief_item_queries(db)
    try:
        # Mirrors the email template: is_sectioned asked once per item, plus
        # the other item-reading properties.
        for _ in range(5):
            _ = loaded.is_sectioned
            _ = loaded.is_sectioned
        _ = loaded.items_by_section
        _ = loaded.reading_time
    finally:
        stop()

    assert len(seen) == 1, (
        f"expected a single brief_item SELECT, got {len(seen)}:\n"
        + "\n".join(seen)
    )


def test_items_are_returned_in_position_order(db):
    _make_brief(db, item_count=4)
    db.session.expunge_all()

    from app.models import DailyBrief
    loaded = DailyBrief.query.one()
    positions = [item.position for item in loaded.ordered_items()]
    assert positions == sorted(positions)
    assert positions == [1, 2, 3, 4]


def test_cache_is_dropped_on_commit_so_writers_never_see_a_stale_list(db):
    """A cached list must not outlive the row state it was built from."""
    from app.models import BriefItem, DailyBrief

    _make_brief(db, item_count=2)
    db.session.expunge_all()
    loaded = DailyBrief.query.one()

    assert len(loaded.ordered_items()) == 2

    db.session.add(BriefItem(
        brief_id=loaded.id, position=3, headline='Late addition', section='world',
    ))
    db.session.commit()  # expire_on_commit fires the invalidation hook

    assert len(loaded.ordered_items()) == 3, (
        "adding an item then re-reading returned the stale cached list"
    )


def test_cache_is_dropped_on_explicit_expire(db):
    from app.models import DailyBrief

    _make_brief(db, item_count=2)
    db.session.expunge_all()
    loaded = DailyBrief.query.one()
    assert len(loaded.ordered_items()) == 2

    db.session.expire(loaded)
    seen, stop = _count_brief_item_queries(db)
    try:
        loaded.ordered_items()
    finally:
        stop()
    assert len(seen) == 1, "expire() must force a refetch"


def test_item_count_does_not_load_every_row(db):
    """item_count runs a COUNT; routing it through the cache would turn brief
    listings into full item loads."""
    _make_brief(db, item_count=6)
    db.session.expunge_all()

    from app.models import DailyBrief
    loaded = DailyBrief.query.one()

    seen, stop = _count_brief_item_queries(db)
    try:
        assert loaded.item_count == 6
    finally:
        stop()

    assert len(seen) == 1
    assert 'count' in seen[0].lower(), (
        f"item_count should aggregate in SQL, not fetch rows: {seen[0]}"
    )


def test_to_dict_uses_the_shared_load(db):
    _make_brief(db, item_count=3)
    db.session.expunge_all()

    from app.models import DailyBrief
    loaded = DailyBrief.query.one()
    _ = loaded.is_sectioned  # warm the cache

    seen, stop = _count_brief_item_queries(db)
    try:
        payload = loaded.to_dict()
    finally:
        stop()

    assert len(payload['items']) == 3
    item_selects = [s for s in seen if 'select' in s.lower() and 'count' not in s.lower()]
    assert item_selects == [], (
        f"to_dict re-queried items instead of reusing the load: {item_selects}"
    )


def test_empty_brief_reads_cleanly(db):
    from app.models import DailyBrief

    _make_brief(db, item_count=0)
    db.session.expunge_all()
    loaded = DailyBrief.query.one()

    assert loaded.ordered_items() == []
    assert loaded.reading_time == 0
    assert loaded.item_count == 0
