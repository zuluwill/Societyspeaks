# AGENTS.md

Conventions for contributors and AI assistants live in [CLAUDE.md](./CLAUDE.md)
(i18n/escaping, SEO, participation/vote semantics). Project overview and the
canonical local-setup steps live in [README.md](./README.md). This file only
adds the non-obvious things that are easy to miss.

## Cursor Cloud specific instructions

This is a single Flask app (`create_app()` in `app/__init__.py`, entrypoint
`run.py`) that hosts several product surfaces (deliberation/consensus,
Programmes, Daily Brief, Paid Briefings, Daily Question, Society Play, Trending
Topics, Partner API/Embeds). Dev dependencies are refreshed automatically by the
Cloud environment update script (Python venv at `venv/`, `npm install`, Tailwind
CSS build, `pybabel compile`). Postgres 16 + Redis are already installed in the
base image, and the local database is already created and populated with the
schema — the notes below are the caveats that are NOT obvious from the README.

### Services are not auto-started — start them per boot

The update script intentionally does not start services. Postgres and Redis must
be started once at the beginning of a session (data persists in the VM
snapshot):

```bash
sudo pg_ctlcluster 16 main start
sudo redis-server --daemonize yes --dir /var/lib/redis
```

Local DB credentials: role `ubuntu` / password `ubuntu`, database
`societyspeaks` (superuser). `redis-cli ping` and `pg_lsclusters` confirm health.

### `.env` is required and is git-ignored

`config.py` calls `load_dotenv()` and hard-fails at import if `DATABASE_URL` is
unset. A local `.env` already exists in the workspace (git-ignored) with:

```
SECRET_KEY=<random>
DATABASE_URL=postgresql://ubuntu:ubuntu@localhost:5432/societyspeaks
REDIS_URL=redis://localhost:6379/0
FLASK_ENV=development
APP_BASE_URL=http://localhost:5000
```

If it is missing, recreate it with those values. In development, Redis is
optional (config falls back to cachelib filesystem sessions + `memory://` rate
limiting) and email/LLM/Stripe/S3 keys are optional (features degrade or no-op).

### Running the app (development)

```bash
source venv/bin/activate
export FLASK_APP=run.py
python run.py        # Werkzeug dev server on 0.0.0.0:5000; run.py monkey-patches gevent
```

Gotcha: do NOT run with a `DATABASE_URL=sqlite:...` left exported in your shell
(the test env uses SQLite in-memory). If SQLite leaks into `run.py` the app
crashes with `Invalid argument(s) 'pool_size'...` because the Postgres pool
options are incompatible with SQLite. `unset DATABASE_URL` before starting the
server so the Postgres URL from `.env` is used.

### Tests (the enforced check; CI = `.github/workflows/tests.yml`)

Tests use SQLite in-memory and in-memory rate limiting (see `tests/conftest.py`),
so no Postgres/Redis is needed. Run them exactly like CI:

```bash
source venv/bin/activate
FLASK_ENV=development DATABASE_URL="sqlite:///:memory:" SECRET_KEY="test-secret-not-for-production" \
  python -m pytest -q
```

Gotcha: run pytest with the repo `.env` moved aside (or `APP_BASE_URL` unset).
Because `config.py` loads `.env`, a dev `APP_BASE_URL=http://localhost:5000`
leaks into the process and makes host-canonicalisation and SEO external-URL
tests fail (they assume the production `societyspeaks.io` base). CI has no `.env`,
which is why it is unaffected.

Known pre-existing failures (also red on `main` CI — NOT caused by setup, do not
"fix" as part of environment work):
- `tests/test_journey_analytics.py` fails at collection: imports
  `compute_topic_rankings` from `app.programmes.journey_analytics`, which is
  referenced (also in `app/commands.py`) but never defined.
- `tests/test_billing_recovery_routes.py::...test_tracks_posthog_when_subscription_past_due`
  fails: the test's PostHog mock doesn't accept the `insert_id` kwarg that
  `app/billing/routes.py` now passes.

With those excluded, the suite is green (~1880 passing). Lint: `ruff` is
configured in `pyproject.toml` but is NOT run in CI and reports thousands of
pre-existing findings — it is not a gate.

### Database schema: build with `create_all`, NOT `flask db upgrade`

`flask db upgrade` from an empty database does NOT work on this repo (the
production DB accumulated drift + repair migrations). Two concrete blockers:
- `f1g2h3i4j5k6` creates indexes on `discussion.bluesky_posted_at` /
  `bluesky_scheduled_at`, but no migration ever adds those columns (added
  directly in prod, like `r1e2p3a4i5r6_repair_missing_columns`).
- Branch-merge drift causes duplicate-column errors (e.g. `country` on
  `news_source`).

The local DB is therefore built from the SQLAlchemy models and stamped at the
Alembic head, so `flask db upgrade` is a clean no-op afterwards. If you ever need
to rebuild it from scratch:

```bash
# 1. create schema from the models
python - <<'PY'
from app import create_app, db
app = create_app(); app.config['SQLALCHEMY_ECHO'] = False
with app.app_context(): db.create_all()
PY
# 2. add the partial UNIQUE indexes the upsert paths need (create_all cannot,
#    because they are partial `WHERE ...` indexes defined only in migrations,
#    not in the model __table_args__). Missing these makes voting 500 with
#    "no unique or exclusion constraint matching the ON CONFLICT specification".
psql "$DATABASE_URL" <<'SQL'
CREATE UNIQUE INDEX IF NOT EXISTS uq_statement_user_vote        ON statement_vote (statement_id, user_id)                 WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_statement_session_vote     ON statement_vote (statement_id, session_fingerprint)     WHERE session_fingerprint IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_discussion_participant_user ON discussion_participant (discussion_id, user_id)        WHERE user_id IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS uq_brief_run_recipient_send    ON brief_email_send (brief_run_id, recipient_id);
SQL
# 3. tell Alembic the DB is current
FLASK_APP=run.py flask db stamp head
```

Note: `flask seed-db` is stale (references the removed `polis_id` column) — do
not rely on it. Create sample data through the UI instead.

### Optional background workers

The in-app APScheduler is disabled outside production
(`is_deployed_production()` requires `DEPLOYED_PRODUCTION=1`). Consensus
clustering and programme exports normally run in a dedicated worker
(`scripts/run_consensus_worker.py`); for local one-off testing you can instead
set `CONSENSUS_ALLOW_IN_PROCESS_EXECUTION=true`. Neither is needed just to run
the web app or the test suite.
