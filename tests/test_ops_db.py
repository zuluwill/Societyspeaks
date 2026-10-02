"""Guardrail: ops/investigation scripts must never get a pooler URL for
direct-only (session-state) operations. Root-cause prevention for the
Neon/PgBouncer ReadOnlySqlTransaction contamination class.
"""
import pytest

from app.lib.ops_db import (
    PoolerUrlError,
    resolve_direct_db_url,
    to_direct_neon_url,
)

_POOLER = "postgresql://u:p@ep-cool-frog-123-pooler.eu-central-1.aws.neon.tech/db?sslmode=require"
_DIRECT = "postgresql://u:p@ep-cool-frog-123.eu-central-1.aws.neon.tech/db?sslmode=require"


def test_to_direct_strips_pooler_segment():
    assert to_direct_neon_url(_POOLER) == _DIRECT
    # Already-direct and non-Neon URLs pass through unchanged.
    assert to_direct_neon_url(_DIRECT) == _DIRECT
    assert to_direct_neon_url("postgresql://u:p@localhost/db") == "postgresql://u:p@localhost/db"
    assert to_direct_neon_url(None) is None


def test_resolve_prefers_explicit_direct_env(monkeypatch):
    monkeypatch.setenv("NEON_DIRECT_DATABASE_URL", _DIRECT)
    monkeypatch.setenv("NEON_OWNER_DATABASE_URL", _POOLER)
    assert resolve_direct_db_url() == _DIRECT


def test_resolve_depoolers_owner_url(monkeypatch):
    monkeypatch.delenv("NEON_DIRECT_DATABASE_URL", raising=False)
    monkeypatch.delenv("DATABASE_URL_DIRECT", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("NEON_DATABASE_URL", raising=False)
    monkeypatch.setenv("NEON_OWNER_DATABASE_URL", _POOLER)
    assert resolve_direct_db_url() == _DIRECT


def test_resolve_fails_closed_on_unstrippable_pooler(monkeypatch):
    # A pooler-marked host our Neon regex can't rewrite must raise, never leak through.
    for var in ("NEON_DIRECT_DATABASE_URL", "DATABASE_URL_DIRECT",
                "NEON_OWNER_DATABASE_URL", "DATABASE_URL", "NEON_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    weird_pooler = "postgresql://u:p@custom-pooler.example.com/db"
    with pytest.raises(PoolerUrlError):
        resolve_direct_db_url(weird_pooler)


def test_resolve_raises_when_no_url(monkeypatch):
    for var in ("NEON_DIRECT_DATABASE_URL", "DATABASE_URL_DIRECT",
                "NEON_OWNER_DATABASE_URL", "DATABASE_URL", "NEON_DATABASE_URL"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(PoolerUrlError):
        resolve_direct_db_url()


def test_direct_url_strips_a_sqlalchemy_driver_suffix(monkeypatch):
    """The result goes to ``psycopg2.connect()``, which libpq parses. An ops
    caller passing ``Config.SQLALCHEMY_DATABASE_URI`` (driver-pinned) must not
    get an unusable DSN."""
    from app.lib.ops_db import resolve_direct_db_url, to_libpq_dsn

    for name in (
        'NEON_DIRECT_DATABASE_URL', 'DATABASE_URL_DIRECT',
        'NEON_OWNER_DATABASE_URL', 'DATABASE_URL', 'NEON_DATABASE_URL',
    ):
        monkeypatch.delenv(name, raising=False)

    resolved = resolve_direct_db_url(
        'postgresql+psycopg2://u:p@ep-abc-123.eu-central-1.aws.neon.tech/db'
    )
    assert resolved.startswith('postgresql://')
    assert '+psycopg2' not in resolved

    assert to_libpq_dsn('postgresql+psycopg://u:p@h/db') == 'postgresql://u:p@h/db'
    assert to_libpq_dsn('postgresql://u:p@h/db') == 'postgresql://u:p@h/db'
    assert to_libpq_dsn('postgres://u:p@h/db') == 'postgres://u:p@h/db'
    assert to_libpq_dsn(None) is None


def test_direct_url_still_refuses_a_pooler_endpoint_after_stripping(monkeypatch):
    """Stripping the driver must not weaken the fail-closed pooler guard."""
    import pytest

    from app.lib.ops_db import PoolerUrlError, resolve_direct_db_url

    for name in (
        'NEON_DIRECT_DATABASE_URL', 'DATABASE_URL_DIRECT',
        'NEON_OWNER_DATABASE_URL', 'DATABASE_URL', 'NEON_DATABASE_URL',
    ):
        monkeypatch.delenv(name, raising=False)

    with pytest.raises(PoolerUrlError):
        resolve_direct_db_url('postgresql+psycopg2://u:p@db-pooler.example.com/db')
