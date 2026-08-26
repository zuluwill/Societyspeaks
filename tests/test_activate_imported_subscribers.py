"""Activation SQL must keep the deliverability ramp timezone-safe by default."""

import pytest

from scripts.activate_imported_subscribers import (
    STACKING_GUARD,
    build_activation_sql,
    build_status_sql,
    stacking_would_hurt,
)


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


def test_status_sql_is_read_only_and_includes_kill_switch():
    sql = build_status_sql(source='b2b_community')
    assert "email_category = 'daily_brief'" in sql
    assert 'bounce_pct' in sql
    assert 'never_sent_waiting' in sql
    assert 'tz_ready_still_imported' in sql
    assert 'UPDATE' not in sql
    assert 'COMMIT' not in sql
    assert "AND source = 'b2b_community'" in sql
    with pytest.raises(ValueError, match='lowercase slug'):
        build_status_sql(source="b2b'; drop table")


def test_activation_sql_rejects_bad_args():
    with pytest.raises(ValueError, match='lowercase slug'):
        build_activation_sql(250, source="b2b'; drop table")
    with pytest.raises(ValueError, match='capped at 1000'):
        build_activation_sql(1001)
    with pytest.raises(ValueError, match='positive'):
        build_activation_sql(0)


def test_stacking_guard_blocks_a_second_first_send_batch():
    # First-send bounce on a new tranche is ~14%. Two 250s in one night
    # would push domain bounce toward the 2% kill-switch.
    assert STACKING_GUARD == 100
    assert STACKING_GUARD < 250
    assert not stacking_would_hurt(0)
    assert not stacking_would_hurt(99)
    assert stacking_would_hurt(100)
    assert stacking_would_hurt(247)
