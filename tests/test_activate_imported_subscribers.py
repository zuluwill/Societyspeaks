"""Activation SQL must keep the deliverability ramp timezone-safe by default."""

import pytest

from scripts.activate_imported_subscribers import build_activation_sql


def test_default_sql_excludes_utc_and_rolls_back():
    sql = build_activation_sql(250, source='b2b_community')
    assert "AND timezone NOT IN ('UTC', 'GMT', 'Etc/UTC')" in sql
    assert "AND timezone LIKE '%/%'" in sql
    assert "AND source = 'b2b_community'" in sql
    assert "LIMIT 250" in sql
    assert "ROLLBACK;" in sql
    assert "COMMIT;" not in sql
    assert "status = 'imported'" in sql
    assert "e.event_type IN ('complained', 'suppressed')" in sql
    assert "lower(coalesce(e.bounce_type, '')) IN ('hard', 'permanent')" in sql


def test_include_utc_drops_timezone_gate():
    sql = build_activation_sql(250, include_utc=True, commit=True)
    batch_sql = sql.split('remaining imported', 1)[0]
    assert 'AND timezone LIKE' not in batch_sql
    assert "timezone NOT IN ('UTC'" not in batch_sql
    assert 'COMMIT;' in sql
    assert 'ROLLBACK;' not in sql


def test_rejects_unsafe_source_and_oversize_batch():
    with pytest.raises(ValueError, match='lowercase slug'):
        build_activation_sql(250, source="b2b'; drop table")
    with pytest.raises(ValueError, match='capped at 1000'):
        build_activation_sql(1001)
    with pytest.raises(ValueError, match='positive'):
        build_activation_sql(0)
