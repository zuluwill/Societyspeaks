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

import logging
import os
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

while not _SHUTDOWN:
    time.sleep(5)

logger.info("Scheduler process exiting cleanly")
sys.exit(0)
