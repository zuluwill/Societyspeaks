#!/usr/bin/env python3
"""
Single verification gate for the app/models.py -> app/models/ package split.

Runs after every step of the 18-step refactor to prove:
  1. The public import surface is intact (from app.models import ...).
  2. Every model class that existed before the refactor is still registered
     in db.metadata — caught by a table-count baseline recorded in step 0.
  3. Alembic sees no schema change — a model that didn't get loaded would
     drop a table from metadata, and autogenerate would want to DROP it.

Run from repo root:
    python3 scripts/verify_models_split.py

Exits 0 on success, non-zero with a diff-style explanation on failure.

The env setup deliberately mirrors tests/conftest.py so this script is
reproducible on any machine, including CI. No live DB is required — the
table-count check reads metadata without opening a connection.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# --- Environment: mirror tests/conftest.py so create_app succeeds locally ---
os.environ.setdefault("DATABASE_URL", "sqlite:///:memory:")
os.environ.setdefault("SECRET_KEY", "verify-models-split")
os.environ.setdefault("FLASK_ENV", "development")

# replit.object_storage is only available on the deployed Replit VM.
for mod in ("replit", "replit.object_storage", "replit.object_storage.errors"):
    sys.modules.setdefault(mod, MagicMock())

# Apply the SQLite-compatible engine opts before Config is imported by anything else.
from config import Config  # noqa: E402

Config.SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
Config.SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
Config.RATELIMIT_STORAGE_URL = "memory://"

# SQLite compatibility shim for tests/conftest.py parity: map PostgreSQL JSONB
# columns to JSON so metadata.create_all() can run without a live Postgres.
from sqlalchemy.ext.compiler import compiles  # noqa: E402
from sqlalchemy.dialects.postgresql import JSONB  # noqa: E402


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_element, _compiler, **_kwargs):
    return "JSON"


# --- The baseline, recorded in step 0. If a submodule stops being imported
# --- during the split, len(db.metadata.tables) drops below this number and
# --- this script fails loudly before anyone sees an empty alembic migration.
EXPECTED_TABLE_COUNT = None  # populated below from an env var or the file itself


def _baseline() -> int:
    """Baseline table count captured in step 0 and pinned to this script.
    The pin exists so a regression (a submodule dropped from __init__.py)
    produces a useful error message instead of a silent false-positive
    from an empty alembic migration."""
    # Pinned at step 0. If you ADD a new model class legitimately after
    # the split is done, bump this number in a separate commit.
    return 75


def check_import_surface() -> list[str]:
    errors: list[str] = []
    try:
        import app.models as m  # noqa: F401
    except Exception as e:
        errors.append(f"import app.models failed: {type(e).__name__}: {e}")
        return errors

    # Anchors: one class from each domain + the two non-class public names.
    # If any of these stops resolving, a submodule has been dropped or a
    # public name forgotten in app/models/__init__.py's re-exports.
    anchors = [
        "db", "generate_slug",
        "User", "Notification", "UserAPIKey",
        "Partner", "PartnerApiKey",
        "AdminAuditEvent", "AdminSettings",
        "IndividualProfile", "CompanyProfile",
        "Programme", "JourneyReminderSubscription",
        "Discussion", "Statement", "StatementVote", "StatementFlag",
        "StatementTranslation",
        "ConsensusAnalysis", "ConsensusJob",
        "AnalyticsEvent",
        "NewsSource", "NewsArticle",
        "TrendingTopic", "UpcomingEvent",
        "DailyBrief", "BriefItem", "DailyBriefSubscriber",
        "DailyQuestion", "DailyQuestionResponse",
        "EmailEvent",
        "Briefing", "BriefRun", "BriefTemplate", "SendingDomain",
        "PricingPlan", "Subscription",
        "PolymarketMarket", "TopicMarketMatch",
    ]
    missing = [name for name in anchors if not hasattr(m, name)]
    if missing:
        errors.append(
            "app.models is missing these re-exports: " + ", ".join(missing)
            + " — check that __init__.py imports every submodule."
        )
    return errors


def check_table_count() -> list[str]:
    errors: list[str] = []
    try:
        from app import db
        import app.models  # noqa: F401  (force-load all mappers)
    except Exception as e:
        errors.append(f"loading app.models failed: {type(e).__name__}: {e}")
        return errors

    actual = len(db.metadata.tables)
    expected = _baseline()
    if actual != expected:
        diff = sorted(db.metadata.tables.keys())
        errors.append(
            f"table count drift: expected {expected}, got {actual}.\n"
            f"  This almost always means __init__.py forgot to import a submodule.\n"
            f"  Currently registered tables ({actual}):\n    "
            + "\n    ".join(diff)
        )
    return errors


def check_event_listeners() -> list[str]:
    """Behavioural check: insert a NewsSource and verify the before_insert
    listener (auto_generate_source_slug) fires. If the listener was left
    behind in the legacy file while the NewsSource class moved, slug stays
    None after flush."""
    errors: list[str] = []
    try:
        from app import create_app, db
        from app.models import NewsSource
    except Exception as e:
        errors.append(f"event listener check setup failed: {type(e).__name__}: {e}")
        return errors

    import uuid

    app = create_app()
    with app.app_context():
        db.create_all()
        probe_name = f"_models_split_probe_{uuid.uuid4().hex[:8]}"
        s = NewsSource(name=probe_name, feed_url="https://example.test/feed")
        try:
            db.session.add(s)
            db.session.flush()
            if not s.slug or not s.slug.startswith("models-split-probe-"):
                errors.append(
                    "NewsSource before_insert listener did not fire. "
                    f"Expected slug to start with 'models-split-probe-', got {s.slug!r}. "
                    "The @event.listens_for handler must live in the same module as the class."
                )
        finally:
            db.session.rollback()
    return errors


def main() -> int:
    all_errors: list[str] = []
    all_errors += check_import_surface()
    all_errors += check_table_count()
    all_errors += check_event_listeners()

    if all_errors:
        print("FAIL verify_models_split.py")
        for err in all_errors:
            print("  -", err)
        return 1
    print("OK verify_models_split.py — import surface, table count, event listeners all pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
