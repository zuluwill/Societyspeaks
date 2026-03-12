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
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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

logger.info("Scheduler process initialised — APScheduler supervisor running in background threads")

_START_TIME = time.time()
_MAX_RUNTIME_SECONDS = 3600  # Proactively restart after 1 hour to keep memory in check
_GC_INTERVAL_TICKS = 6       # gc.collect() every 6 ticks × 5 s = every 30 seconds
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

    # Proactive clean restart: exit cleanly so the restart loop in the
    # deployment command gives this process a fresh memory slate.  This
    # prevents the gradual growth that caused the ~45-minute SIGBUS crash.
    if time.time() - _START_TIME > _MAX_RUNTIME_SECONDS:
        logger.info(
            "Scheduler process reached max runtime (%dh) — exiting cleanly for restart",
            _MAX_RUNTIME_SECONDS // 3600,
        )
        break

logger.info("Scheduler process exiting cleanly")
sys.exit(0)
