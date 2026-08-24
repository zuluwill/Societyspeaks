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
base image — the notes below are the caveats that are NOT obvious from the README.

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

### Database schema — use `flask db upgrade` (same as production)

Canonical path matches production (`scripts/start.sh`):

```bash
source venv/bin/activate
export FLASK_APP=run.py
flask db upgrade
# optional sample discussion:
flask seed-db
```

From-empty installs work through current head. Historical mid-chain migrations
that assumed production-only drift are idempotent (`IF NOT EXISTS` /
table-exists guards) so they no-op safely on fresh databases and are never
re-executed on production (those revision IDs are already stamped). Head
`30a9831d56e0` is an idempotent repair that creates billing/briefing analytics
tables and columns that existed only on models (or via `create_all` / sibling
branches) — safe on production that already has them. After upgrade,
`DATABASE_URL=… python scripts/check_schema_drift.py` should report **no HIGH**
drift (LOW/cosmetic index naming differences are OK).

Partial unique indexes required by vote `ON CONFLICT` upserts
(`uq_statement_user_vote`, `uq_statement_session_vote`,
`uq_discussion_participant_user`) are created by migration `v1w2x3y4z5a6` and
are also declared on the models so `db.create_all()` (tests) matches.

### Running the app (development)

```bash
source venv/bin/activate
export FLASK_APP=run.py
# Important: unset any leftover test DATABASE_URL=sqlite://… from your shell
unset DATABASE_URL
python run.py        # Werkzeug dev server on 0.0.0.0:5000; run.py monkey-patches gevent
```

Gotcha: if SQLite leaks into `run.py` the app crashes with
`Invalid argument(s) 'pool_size'…` because Postgres pool options are incompatible
with SQLite. Always `unset DATABASE_URL` so the Postgres URL from `.env` is used.

### Tests (the enforced check; CI = `.github/workflows/tests.yml`)

Tests use SQLite in-memory and in-memory rate limiting (see `tests/conftest.py`),
so no Postgres/Redis is needed. Run them exactly like CI:

```bash
source venv/bin/activate
# Move .env aside (or unset APP_BASE_URL) — load_dotenv() would otherwise
# leak the local APP_BASE_URL into host-canonicalisation / SEO tests.
mv .env .env.bak
FLASK_ENV=development DATABASE_URL="sqlite:///:memory:" SECRET_KEY="test-secret-not-for-production" \
  python -m pytest -q
mv .env.bak .env
```

Lint: `ruff` is configured in `pyproject.toml` but is NOT run in CI and reports
thousands of pre-existing findings — it is not a gate.

### Optional background workers

The in-app APScheduler is disabled outside production
(`is_deployed_production()` requires `DEPLOYED_PRODUCTION=1`). Consensus
clustering and programme exports normally run in a dedicated worker
(`scripts/run_consensus_worker.py`); for local one-off testing you can instead
set `CONSENSUS_ALLOW_IN_PROCESS_EXECUTION=true`. Neither is needed just to run
the web app or the test suite.
