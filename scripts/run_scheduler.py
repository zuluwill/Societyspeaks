#!/usr/bin/env python3
"""
Standalone scheduler process for role-separated deployments.

Run as:
    APP_ROLE=scheduler python3 scripts/run_scheduler.py

This process initialises the Flask application context and lets the in-app
APScheduler supervisor thread (defined in app/__init__.py) take the Redis
lock and drive all background jobs.  It never serves HTTP — gunicorn handles
that in a parallel process with APP_ROLE=web.

The main thread parks in a sleep loop so that the daemon scheduler threads
stay alive.  SIGTERM/SIGINT trigger a clean shutdown.
"""

import gc
import logging
import os
import resource
import signal
import socket as _socket
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# IPv4-preference patch — see run.py for full rationale.
_orig_getaddrinfo = _socket.getaddrinfo


def _prefer_ipv4(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
    results = _orig_getaddrinfo(host, port, family, type, proto, flags)
    if family == 0 and port is not None:
        ipv4 = [r for r in results if r[0] == _socket.AF_INET]
        if ipv4:
            return ipv4
    return results


_socket.getaddrinfo = _prefer_ipv4

os.environ.setdefault("APP_ROLE", "scheduler")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("scheduler_process")

_SHUTDOWN = False


def _handle_signal(signum, _frame):
    global _SHUTDOWN
    logger.info("Scheduler process received signal %s — shutting down", signum)
    _SHUTDOWN = True


signal.signal(signal.SIGTERM, _handle_signal)
signal.signal(signal.SIGINT, _handle_signal)

logger.info("Scheduler process starting (APP_ROLE=%s)", os.environ.get("APP_ROLE"))

from app import create_app  # noqa: E402

app = create_app()

# Import running-job tracker AFTER create_app() so init_scheduler() has run
from app.scheduler import _running_jobs, _running_jobs_lock, scheduler as apscheduler  # noqa: E402

logger.info("Scheduler process initialised — APScheduler supervisor running in background threads")

_START_TIME = time.time()
_MAX_RUNTIME_SECONDS = 1800  # Proactively restart after 30 min — SIGBUS crashes occur at ~45 min
_GC_INTERVAL_TICKS = 2       # gc.collect() every 2 ticks × 5 s = every 10 seconds
_MEM_LOG_INTERVAL_TICKS = 60 # Log RSS every 60 ticks × 5 s = every 5 minutes
_tick = 0

while not _SHUTDOWN:
    time.sleep(5)
    _tick += 1

    # Periodic garbage collection: Python's GC runs on allocation count, not
    # time.  In a long-running multi-threaded scheduler the cycle detector can
    # fall behind.  Forcing a full collection every 30 s keeps cyclic garbage
    # (e.g. SQLAlchemy result proxy chains, traceback frames held by exc_info
    # loggers) from accumulating between ticks.
    #
    # gc.collect() alone does not shrink the process RSS — Python's allocator
    # holds freed arenas for reuse.  malloc_trim(0) tells glibc to release
    # contiguous free pages at the top of the heap back to the OS, which is
    # the only way to lower the measured RSS without restarting the process.
    if _tick % _GC_INTERVAL_TICKS == 0:
        gc.collect()
        try:
            import ctypes
            ctypes.CDLL("libc.so.6").malloc_trim(0)
        except Exception:
            pass  # Not available on non-glibc platforms (macOS, musl) — safe to skip

    # Memory monitoring: log RSS usage every 5 minutes so we can track growth
    # trends across deployments.  resource.getrusage().ru_maxrss is in KB on
    # Linux (pages on macOS, but this code only runs on the Replit Linux VM).
    if _tick % _MEM_LOG_INTERVAL_TICKS == 0:
        try:
            rss_mb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            uptime_min = (time.time() - _START_TIME) / 60
            logger.info(
                "Scheduler memory: RSS=%.1f MB  uptime=%.1f min",
                rss_mb,
                uptime_min,
            )
        except Exception:
            pass

    # Proactive clean restart: exit cleanly so the deployment restart loop
    # gives this process a fresh memory slate.  This prevents the gradual
    # growth that caused the ~45-minute SIGBUS crash.
    #
    # Safety: we never restart while a job is mid-flight (email sends, brief
    # generation, trending pipeline).  We wait up to 5 extra minutes for any
    # active job to finish, then exit regardless to avoid being permanently
    # stuck behind a stalled job.
    if time.time() - _START_TIME > _MAX_RUNTIME_SECONDS:
        _SAFE_RESTART_DEADLINE = _MAX_RUNTIME_SECONDS + 300  # +5 min grace
        with _running_jobs_lock:
            active = set(_running_jobs)
        if active:
            elapsed = time.time() - _START_TIME
            if elapsed < _SAFE_RESTART_DEADLINE:
                logger.info(
                    "Max runtime reached but %d job(s) still running (%s) — "
                    "waiting for clean completion (grace period: %ds left)",
                    len(active),
                    ", ".join(sorted(active)),
                    int(_SAFE_RESTART_DEADLINE - elapsed),
                )
                continue  # stay in loop, check again next tick
            else:
                logger.warning(
                    "Grace period expired with %d job(s) still running (%s) — "
                    "forcing restart to prevent memory growth",
                    len(active),
                    ", ".join(sorted(active)),
                )
        logger.info(
            "Scheduler process reached max runtime (%d min) — exiting cleanly for restart",
            _MAX_RUNTIME_SECONDS // 60,
        )
        break

logger.info("Scheduler process exiting cleanly")

# Explicitly stop APScheduler's job-dispatch loop before sys.exit() so the
# background thread pool is drained gracefully.  Without this, APScheduler's
# _process_jobs loop keeps firing after Python starts tearing down the process,
# causing "RuntimeError: cannot schedule new futures after shutdown" spam.
try:
    if apscheduler is not None and apscheduler.running:
        apscheduler.shutdown(wait=False)
        logger.info("APScheduler shut down cleanly")
except Exception as exc:
    logger.warning("APScheduler shutdown warning (non-fatal): %s", exc)

# Release the Redis scheduler lock before exiting so the replacement process
# can acquire it immediately rather than waiting up to TTL=120 s for it to
# expire naturally.
#
# Normally the lock is managed and renewed by the heartbeat thread inside
# _run_scheduler_cycle() (app/__init__.py).  sys.exit() kills all daemon
# threads instantly, so their finally blocks never run.  Without this
# explicit release the next process sees the lock still held (e.g.
# "Scheduler lock held by pid=NNN, ttl=78s, retrying (1/8)...") and waits
# up to 120 s before it can acquire it — adding unnecessary dead time.
#
# The Lua CAS script ensures we only delete the key if we still own it
# (another process cannot accidentally release a lock it doesn't hold).
_SCHEDULER_LOCK_KEY = 'scheduler_lock'
try:
    _redis_url = os.environ.get('REDIS_URL', '')
    if _redis_url:
        import redis as _redis_lib
        _rc = _redis_lib.from_url(_redis_url, socket_timeout=3, socket_connect_timeout=3)
        _release_script = """
if redis.call('get', KEYS[1]) == ARGV[1] then
    return redis.call('del', KEYS[1])
else
    return 0
end
"""
        _owned_by = str(os.getpid())
        _result = _rc.eval(_release_script, 1, _SCHEDULER_LOCK_KEY, _owned_by)
        if _result:
            logger.info("Scheduler Redis lock released (pid=%s)", _owned_by)
        else:
            logger.info(
                "Scheduler Redis lock not held by this process (pid=%s) — nothing to release",
                _owned_by,
            )
except Exception as _lock_err:
    logger.warning("Could not release Redis lock before exit (non-fatal): %s", _lock_err)

sys.exit(0)
