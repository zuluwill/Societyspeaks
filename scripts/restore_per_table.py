#!/usr/bin/env python3
"""
Resumable per-table restore. Skips tables that already have data.
Uses pg_restore --table=<name> to extract one table at a time.
"""
import os, re, subprocess, time, sys
import psycopg2

DATABASE_URL = os.environ["DATABASE_URL"]
DUMP_FILE = "/home/runner/workspace/still-fire_070826_backup.dump"

LOG = open("/tmp/restore_py.log", "w", buffering=1)
def log(msg):
    LOG.write(msg + "\n"); LOG.flush()

sys.stderr = LOG

log(f"Per-table restore: {DUMP_FILE}")
conn = psycopg2.connect(DATABASE_URL, connect_timeout=30)
conn.autocommit = True
cur = conn.cursor()
log("Connected OK")

# Disable FK enforcement for this session (same as pg_restore does internally)
cur.execute("SET session_replication_role = 'replica'")

# --- Get ordered table list from dump TOC ---
toc_out = subprocess.check_output(
    ["pg_restore", "--list", DUMP_FILE], stderr=subprocess.DEVNULL, text=True
)
tables_in_dump = []
for line in toc_out.splitlines():
    if "TABLE DATA" in line:
        parts = line.strip().split()
        try:
            idx = parts.index("DATA") + 2   # "TABLE DATA public <name> owner"
            tables_in_dump.append(parts[idx])
        except (ValueError, IndexError):
            pass
log(f"Tables in dump: {len(tables_in_dump)}")

# --- Identify which tables need restoring ---
tables_to_restore = []
for t in tables_in_dump:
    try:
        cur.execute(f'SELECT COUNT(*) FROM "{t}"')
        cnt = cur.fetchone()[0]
        if cnt == 0:
            tables_to_restore.append(t)
        else:
            log(f"  SKIP {t} ({cnt} rows already present)")
    except Exception as e:
        conn.rollback()
        log(f"  WARN count {t}: {e} — will attempt restore")
        tables_to_restore.append(t)

log(f"\nTables to restore: {len(tables_to_restore)}\n")

# --- Streaming file-like object for COPY FROM STDIN ---
class CopyStream:
    def __init__(self, line_iter):
        self._iter = line_iter
        self._buf  = ""
        self._done = False

    def _next_raw(self):
        if self._done:
            return None
        try:
            line = next(self._iter)
        except StopIteration:
            self._done = True
            return None
        if line.rstrip("\n") == "\\.":
            self._done = True
            return None
        return line

    def read(self, size=-1):
        if self._done and not self._buf:
            return ""
        if size == -1:
            chunks = [self._buf]; self._buf = ""
            while True:
                l = self._next_raw()
                if l is None: break
                chunks.append(l)
            return "".join(chunks)
        result = []; remaining = size
        if self._buf:
            chunk = self._buf[:remaining]; self._buf = self._buf[remaining:]
            result.append(chunk); remaining -= len(chunk)
        while remaining > 0 and not self._done:
            l = self._next_raw()
            if l is None: break
            if len(l) <= remaining:
                result.append(l); remaining -= len(l)
            else:
                result.append(l[:remaining]); self._buf = l[remaining:]; remaining = 0
        return "".join(result)

    def readline(self):
        if self._done and not self._buf:
            return ""
        if self._buf:
            idx = self._buf.find("\n")
            if idx >= 0:
                line = self._buf[:idx+1]; self._buf = self._buf[idx+1:]; return line
            prefix = self._buf; self._buf = ""
            l = self._next_raw()
            return prefix if l is None else prefix + l
        l = self._next_raw()
        return "" if l is None else l

    def exhaust(self):
        while not self._done:
            self._next_raw()

# --- Restore each empty table ---
start   = time.time()
done    = 0
skipped = 0
errors  = 0

for tname in tables_to_restore:
    t_start = time.time()
    log(f"Restoring: {tname}")

    try:
        proc = subprocess.Popen(
            ["pg_restore", "--no-owner", "--no-acl", "-a",
             f"--table={tname}", "-f", "-", DUMP_FILE],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1,
        )

        line_iter  = iter(proc.stdout)
        found_copy = False

        for line in line_iter:
            stripped = line.strip()
            upper    = stripped.upper()
            if upper.startswith("COPY ") and "FROM STDIN" in upper:
                found_copy = True
                # TRUNCATE first so re-runs are idempotent
                try:
                    cur.execute(f'TRUNCATE TABLE "{tname}" CASCADE')
                except psycopg2.Error as te:
                    log(f"  WARN TRUNCATE {tname}: {te}")
                    conn.rollback()

                stream = CopyStream(line_iter)
                try:
                    cur.copy_expert(stripped, stream)
                    done += 1
                    log(f"  OK  {tname} ({time.time()-t_start:.1f}s)")
                except psycopg2.Error as ce:
                    stream.exhaust()
                    log(f"  COPY ERR {tname}: {str(ce).strip()[:200]}")
                    errors += 1
                    try: conn.rollback()
                    except: pass
                break  # only one COPY block per table

        if not found_copy:
            log(f"  INFO no COPY block for {tname} (empty in dump)")
            skipped += 1

        proc.stdout.close()
        proc.stderr.read()
        proc.wait()

    except Exception as ex:
        import traceback
        log(f"  FATAL {tname}: {ex}\n{traceback.format_exc()}")
        errors += 1

# Re-enable FK checks
try:
    cur.execute("SET session_replication_role = 'DEFAULT'")
except: pass

cur.close(); conn.close()
total = time.time() - start
log(f"\n{'='*55}")
log(f"Finished in {total:.1f}s")
log(f"  Restored : {done}")
log(f"  Skipped  : {skipped}")
log(f"  Errors   : {errors}")
log("="*55)
LOG.close()
