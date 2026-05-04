#!/usr/bin/env python3
"""
Dedicated consensus queue worker.

Runs outside APScheduler/web request processes so sklearn clustering does not
block scheduler orchestration or web traffic.
"""

import logging
import os
import signal
import sys
import time

# Ensure the workspace root is on sys.path so `app` can be imported
# regardless of the working directory the workflow runner uses.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# IPv4-preference patch — single source of truth lives in app/lib/network_patches.
# Must run before create_app() (which opens the SESSION_REDIS pool and pings it).
from app.lib.network_patches import apply_ipv4_preference  # noqa: E402
apply_ipv4_preference()

# Ensure this process never starts the in-app scheduler.
os.environ.setdefault("DISABLE_SCHEDULER", "1")
# Mark this process as the approved heavy-consensus worker context.
os.environ.setdefault("CONSENSUS_WORKER_PROCESS", "1")

from app import create_app, db  # noqa: E402
from app.discussions.jobs import process_next_consensus_job, mark_stale_consensus_jobs, get_consensus_queue_metrics  # noqa: E402
from app.programmes.export_jobs import (
    process_next_programme_export_job,
    mark_stale_programme_export_jobs,
    get_programme_export_queue_metrics,
)  # noqa: E402


logger = logging.getLogger("consensus_worker")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
_RUNNING = True


def _worker_id():
    configured = (os.getenv("CONSENSUS_WORKER_ID") or "").strip()
    if configured:
        return configured
    return f"pid-{os.getpid()}"


def _handle_shutdown(signum, _frame):
    global _RUNNING
    logger.info(f"Consensus worker received signal {signum}; shutting down.")
    _RUNNING = False


def _publish_heartbeat(worker_id):
    """Publish a heartbeat for this worker via the shared Redis pool.

    Resolving the client through ``get_client()`` on every tick is a cheap
    dict lookup once the pool is warm, and it self-heals if the pool was
    not available at worker start.
    """
    try:
        from app.lib.redis_client import get_client
        redis_client = get_client(decode_responses=False)
    except Exception as exc:
        logger.debug(f"Consensus worker heartbeat client unavailable: {exc}")
        return
    if not redis_client:
        return
    try:
        now_ts = str(int(time.time()))
        # Per-worker heartbeat key for horizontal worker pool visibility.
        redis_client.setex(f"consensus_worker:heartbeat:{worker_id}", 120, now_ts)
        # Backward-compatible single key used by existing monitors/tests.
        redis_client.setex("consensus_worker:last_heartbeat_at", 120, now_ts)
    except Exception as exc:
        logger.debug(f"Consensus worker heartbeat failed: {exc}")


def main():
    app = create_app()
    worker_id = _worker_id()
    signal.signal(signal.SIGTERM, _handle_shutdown)
    signal.signal(signal.SIGINT, _handle_shutdown)

    idle_sleep = max(0.1, float(app.config.get("CONSENSUS_WORKER_IDLE_SLEEP_SECONDS", 2.0)))
    active_sleep = max(0.0, float(app.config.get("CONSENSUS_WORKER_ACTIVE_SLEEP_SECONDS", 0.2)))
    metrics_interval = max(5, int(app.config.get("CONSENSUS_WORKER_METRICS_INTERVAL_SECONDS", 30)))

    last_metrics_at = 0.0
    last_stale_at = 0.0
    last_export_stale_at = 0.0
    stale_sweep_interval = 60  # stale timeout is 900s; sweeping more often adds no value

    logger.info(f"Consensus worker started (id={worker_id}).")
    with app.app_context():
        while _RUNNING:
            try:
                _publish_heartbeat(worker_id)
                now = time.time()
                if (now - last_stale_at) >= stale_sweep_interval:
                    stale_count = mark_stale_consensus_jobs()
                    if stale_count:
                        logger.warning(f"Marked {stale_count} stale consensus jobs")
                    last_stale_at = now
                if (now - last_export_stale_at) >= stale_sweep_interval:
                    stale_export_count = mark_stale_programme_export_jobs()
                    if stale_export_count:
                        logger.warning(f"Marked {stale_export_count} stale programme export jobs")
                    last_export_stale_at = now

                processed_consensus = process_next_consensus_job()
                processed_export = process_next_programme_export_job()
                processed = bool(processed_consensus or processed_export)
                now = time.time()
                if (now - last_metrics_at) >= metrics_interval:
                    consensus_metrics = get_consensus_queue_metrics()
                    export_metrics = get_programme_export_queue_metrics()
                    logger.info(
                        f"Queue metrics (worker_id={worker_id}): "
                        f"consensus(queued={consensus_metrics['queued_count']}, running={consensus_metrics['running_count']}, "
                        f"dead_letter={consensus_metrics['dead_letter_count']}, lag_s={consensus_metrics['queue_lag_seconds']}) "
                        f"exports(queued={export_metrics['queued_count']}, running={export_metrics['running_count']}, "
                        f"dead_letter={export_metrics['dead_letter_count']}, lag_s={export_metrics['queue_lag_seconds']})"
                    )
                    last_metrics_at = now

                time.sleep(active_sleep if processed else idle_sleep)
            except Exception as exc:
                logger.error(f"Consensus worker loop error: {exc}", exc_info=True)
                db.session.rollback()
                time.sleep(idle_sleep)

    logger.info(f"Consensus worker stopped (id={worker_id}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
