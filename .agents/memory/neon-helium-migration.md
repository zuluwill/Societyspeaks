---
name: Neon → Helium migration recovery
description: How the June 2026 Neon deprecation caused an outage and how we recovered
---

## Rule
After Replit's Helium migration (deadline June 8, 2026), `NEON_DATABASE_URL` points to a defunct endpoint. `config.py` line 117 must use ONLY `os.getenv('DATABASE_URL')` — never `os.getenv('NEON_DATABASE_URL') or os.getenv('DATABASE_URL')`.

**Why:** A prior agent (May 22, 2026) changed `config.py` to prefer `NEON_DATABASE_URL`. When Neon deprecated that endpoint on June 8, every app start failed with a connection error even though `DATABASE_URL` (Helium) was fine.

**How to apply:** If the app can't connect to the DB after July 2026, check `config.py` first — ensure `SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL')` with no Neon fallback.

## Recovery technique: per-table resumable restore via workflow
When a 633MB custom-format pg_dump needs to be loaded into Helium (which only accepts psycopg2, not pg_restore binary connections):

1. Write `scripts/restore_per_table.py` — checks which tables already have rows, skips them, uses `pg_restore -a --table=<name>` per table + `CopyStream` streaming to avoid OOM
2. Run it as a **Replit workflow** (not a background shell process) — background processes get SIGKILL'd after ~2 min; workflows survive
3. Script is resumable: re-run the workflow if it gets killed mid-table (that table rolls back, next run picks it up)
4. Use `SET session_replication_role = 'replica'` to disable FK enforcement during restore
5. The workflow finishes with a "Restored N / Errors 0" summary in `/tmp/restore_py.log`

**Why background processes fail:** `setsid + disown` prevents SIGHUP but Replit's sandbox still sends SIGKILL to orphan processes after ~120s. Workflows are exempt from this limit.
