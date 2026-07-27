"""Migration safety for multi-service deploys.

``wk001`` adds ``brief_item.weekly_development``. SQLAlchemy selects every mapped
column, so a service running the new code before that migration lands fails on
*every* ``BriefItem`` query — daily brief sends and all brief pages, not just the
weekly. Two guards cover the window:

- ``assert_db_at_head`` stops a worker booting against a stale schema.
- ``acquire_migration_lock`` stops the two ``preDeployCommand: flask db upgrade``
  declarations (web + scheduler in render.yaml) racing each other.

Both are fail-closed and run at deploy time, where a bug is expensive and
invisible until it bites — hence the coverage.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.lib.db_migration_guard import (
    MIGRATION_ADVISORY_LOCK_KEY,
    acquire_migration_lock,
    assert_db_at_head,
)


REPO_ROOT = Path(__file__).resolve().parents[1]


def _connection(dialect_name):
    return SimpleNamespace(
        dialect=SimpleNamespace(name=dialect_name),
        execute=MagicMock(),
    )


# --------------------------------------------------------------------------
# acquire_migration_lock
# --------------------------------------------------------------------------

def test_lock_is_taken_on_postgresql():
    conn = _connection('postgresql')
    assert acquire_migration_lock(conn) is True
    conn.execute.assert_called_once()

    stmt, params = conn.execute.call_args[0]
    assert 'pg_advisory_xact_lock' in str(stmt)
    assert params == {'key': MIGRATION_ADVISORY_LOCK_KEY}


def test_lock_is_a_transaction_lock_so_it_cannot_be_stranded():
    """Session-scoped locks survive a crashed migration; xact locks do not."""
    conn = _connection('postgresql')
    acquire_migration_lock(conn)
    stmt = str(conn.execute.call_args[0][0])
    assert 'pg_advisory_xact_lock' in stmt
    assert 'pg_advisory_lock(' not in stmt


@pytest.mark.parametrize('dialect', ['sqlite', 'mysql'])
def test_lock_no_ops_on_other_backends(dialect):
    conn = _connection(dialect)
    assert acquire_migration_lock(conn) is False
    assert not conn.execute.called


def test_lock_key_fits_in_a_postgres_bigint():
    assert -(2 ** 63) <= MIGRATION_ADVISORY_LOCK_KEY < 2 ** 63


# --------------------------------------------------------------------------
# assert_db_at_head
# --------------------------------------------------------------------------

def _run_guard(app, current_revision, **kwargs):
    with patch(
        'app.lib.db_migration_guard._current_db_revision',
        return_value=current_revision,
    ):
        return assert_db_at_head(app, **kwargs)


def _alembic_head():
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option('script_location', str(REPO_ROOT / 'migrations'))
    return ScriptDirectory.from_config(config).get_heads()[0]


def test_boots_when_db_is_at_head(app):
    _run_guard(app, _alembic_head())  # must not raise


def test_refuses_to_start_on_a_stale_revision(app):
    with pytest.raises(SystemExit) as exc:
        _run_guard(app, 'dq004')
    assert exc.value.code == 1


def test_refuses_to_start_on_an_unmigrated_database(app):
    """current_revision is None before any migration has ever run."""
    with pytest.raises(SystemExit) as exc:
        _run_guard(app, None)
    assert exc.value.code == 1


def test_failure_message_names_the_role_and_the_fix(app, caplog):
    with caplog.at_level('CRITICAL'):
        with pytest.raises(SystemExit):
            _run_guard(app, 'dq004', role='scheduler')

    message = ' '.join(r.message for r in caplog.records)
    assert 'scheduler' in message
    assert 'flask db upgrade' in message
    assert 'dq004' in message


def test_escape_hatch_skips_the_check(app, monkeypatch):
    monkeypatch.setenv('SKIP_DB_MIGRATION_GUARD', '1')
    _run_guard(app, 'dq004')  # stale, but explicitly skipped


@pytest.mark.parametrize('value', ['0', 'false', 'no', ''])
def test_escape_hatch_is_not_triggered_by_falsey_values(app, monkeypatch, value):
    monkeypatch.setenv('SKIP_DB_MIGRATION_GUARD', value)
    with pytest.raises(SystemExit):
        _run_guard(app, 'dq004')


def test_repo_has_exactly_one_alembic_head():
    """Multiple heads would make the guard's `current in heads` check ambiguous
    and mean `flask db upgrade` cannot resolve a single target."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config()
    config.set_main_option('script_location', str(REPO_ROOT / 'migrations'))
    heads = ScriptDirectory.from_config(config).get_heads()
    assert len(heads) == 1, f"expected a single head, found {heads}"


# --------------------------------------------------------------------------
# Wiring — the guards are worthless if nothing calls them
# --------------------------------------------------------------------------

def test_scheduler_entrypoint_calls_the_guard_before_running_jobs():
    src = (REPO_ROOT / 'scripts' / 'run_scheduler.py').read_text(encoding='utf-8')
    assert 'assert_db_at_head' in src
    assert src.index('assert_db_at_head(app') < src.index('from app.scheduler import')


def test_alembic_env_takes_the_lock_before_running_migrations():
    """Scoped to run_migrations_online: offline mode emits SQL without executing
    it, so it has no concurrency to serialise and takes no lock."""
    src = (REPO_ROOT / 'migrations' / 'env.py').read_text(encoding='utf-8')
    online = src[src.index('def run_migrations_online'):]

    assert 'acquire_migration_lock(connection)' in online
    assert online.index('acquire_migration_lock(connection)') < online.index(
        'context.run_migrations()'
    )


def test_both_services_declaring_predeploy_are_covered_by_the_lock():
    """render.yaml declares `flask db upgrade` twice — that is only safe with the lock."""
    render = (REPO_ROOT / 'render.yaml').read_text(encoding='utf-8')
    env_src = (REPO_ROOT / 'migrations' / 'env.py').read_text(encoding='utf-8')

    predeploy_count = render.count('preDeployCommand: flask db upgrade')
    if predeploy_count > 1:
        assert 'acquire_migration_lock' in env_src, (
            f"{predeploy_count} services run `flask db upgrade` concurrently but "
            f"migrations/env.py takes no advisory lock"
        )
