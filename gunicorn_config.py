import logging
import os

bind = "0.0.0.0:5000"
_workers_raw = (os.getenv("WEB_CONCURRENCY") or os.getenv("GUNICORN_WORKERS") or "4").strip()
try:
    workers = max(1, int(_workers_raw))
except ValueError:
    workers = 4
reuse_port = True
timeout = 120
worker_class = "gevent"
worker_connections = 1000

# Recycle each worker after this many requests (± jitter). This bounds
# per-request memory accumulation (greenlet overhead, lazy imports, SQLAlchemy
# session fragments) that never gets freed in a long-running worker.
# Gunicorn forks a replacement before killing the old worker, so there is no
# gap in request handling — *provided* worker_exit returns quickly. Do not
# lower this to "fix" health-check emails; hung PostHog shutdown was the
# cause (see shutdown_server_posthog). Jitter keeps the three workers from
# recycling in lockstep after a simultaneous start.
max_requests = 1000
max_requests_jitter = 300

# DO NOT preload. With preload_app=True, run.py's monkey.patch_all() executes
# in the gunicorn MASTER, replacing os.fork/os.waitpid/SIGCHLD handling with
# gevent versions that the arbiter's reaping loop cannot use. Every worker
# that exits (max_requests recycle, deploy SIGTERM) then becomes a zombie the
# master never reaps: no replacement is spawned, the stale heartbeat is logged
# as a phantom "WORKER TIMEOUT" ~120s later, capacity decays worker by worker
# until /health fails and Render restarts the container ("connection refused"
# alerts, every ~90 min in production). Reproduced and bisected locally
# 2026-07-10: patched-master+preload hangs; either alone recycles cleanly.
#
# With preload off, gunicorn's gevent worker runs monkey.patch_all() itself in
# each child (workers/ggevent.py init_process) BEFORE the app imports
# ssl/socket/threading in load_wsgi, so the original ssl-patching concern is
# still covered; run.py's own patch is then a harmless re-patch that keeps
# direct `python run.py` runs working. psycogreen and the IPv4 patch run at
# app import inside the worker, after patching — correct order.
#
# No pre-fork state also means no shared-socket hazard: SQLAlchemy, Redis
# session/cache pools and the PostHog client are all created per-worker, so
# the old post_fork reset hooks are unnecessary and were removed.
preload_app = False


# Dump stacks 30s before gunicorn's 120s timeout kill so the culprit is in
# the logs even when the worker never becomes responsive again.
#
# MUST start from post_worker_init, not post_fork: GeventWorker.init_process()
# calls hub.reinit() after post_fork, which destroys any greenlets spawned
# there. Without the re-armer, the one-shot faulthandler timer would fire
# after 90s on a healthy worker (false-positive stack spam).
_STALL_DUMP_AFTER_SECONDS = timeout - 30
_STALL_REARM_INTERVAL_SECONDS = 30
_stall_watchdog_started = False


def _dump_gevent_run_info(label, worker_pid):
    """Print all greenlet stacks (gevent-aware). Best-effort; never raises."""
    import sys

    try:
        from gevent import util as gevent_util

        sys.stderr.write(
            f"\n=== {label} [{worker_pid}]: gevent greenlet run info ===\n"
        )
        sys.stderr.write("\n".join(gevent_util.format_run_info()))
        sys.stderr.write("\n")
        sys.stderr.flush()
    except Exception as exc:
        logging.getLogger("gunicorn.error").warning(
            "%s [%s]: gevent run-info dump failed: %s", label, worker_pid, exc
        )


def worker_abort(worker):
    """Dump stacks when gunicorn aborts a worker after WORKER TIMEOUT.

    The arbiter sends SIGABRT before SIGKILL. This runs (GIL permitting) at
    the kill moment. faulthandler covers OS threads (incl. a GIL-holding C
    call on the hub thread); gevent.util.format_run_info covers sibling
    greenlets that faulthandler cannot see.
    """
    import faulthandler
    import sys

    logging.getLogger("gunicorn.error").error(
        "worker_abort [%s]: WORKER TIMEOUT — dumping thread + greenlet stacks",
        worker.pid,
    )
    try:
        faulthandler.dump_traceback(file=sys.stderr, all_threads=True)
    except Exception:
        pass
    _dump_gevent_run_info("worker_abort", worker.pid)


def _start_stall_watchdog(worker_pid):
    """Arm a C-level watchdog that dumps stacks if the gevent hub stalls.

    faulthandler.dump_traceback_later() runs on a native thread and dumps
    without needing the GIL, so it fires even when the hub is wedged inside a
    C call (regex backtracking, numpy/sklearn, etc.) where the Python-level
    SIGABRT handler in worker_abort() cannot run.  A greenlet re-arms the
    timer every _STALL_REARM_INTERVAL_SECONDS; each dump_traceback_later()
    call replaces the previous timer, so nothing prints while the event loop
    is healthy.  If the loop blocks for _STALL_DUMP_AFTER_SECONDS the re-armer
    can't run, the deadline passes, and the stacks land in stderr ~30s before
    gunicorn's timeout kill.
    """
    global _stall_watchdog_started

    import faulthandler
    import sys

    import gevent

    if _stall_watchdog_started:
        return

    faulthandler.cancel_dump_traceback_later()
    faulthandler.dump_traceback_later(_STALL_DUMP_AFTER_SECONDS, file=sys.stderr)

    def _rearm():
        while True:
            gevent.sleep(_STALL_REARM_INTERVAL_SECONDS)
            faulthandler.dump_traceback_later(_STALL_DUMP_AFTER_SECONDS, file=sys.stderr)

    gevent.spawn(_rearm)
    _stall_watchdog_started = True
    logging.getLogger("gunicorn.error").info(
        "post_worker_init [%s]: hub stall watchdog armed "
        "(dump after %ss of event-loop blockage)",
        worker_pid,
        _STALL_DUMP_AFTER_SECONDS,
    )


def _ensure_gevent_monitor(worker_pid):
    """Start gevent's blocking monitor if env enabled it but the hub never did.

    GEVENT_MONITOR_THREAD_ENABLE is read at gevent import time. Under gunicorn
    the hub is reinit()'d after fork; starting explicitly here guarantees the
    monitor is attached to the worker hub that actually serves requests.
    """
    import os

    enabled = os.environ.get("GEVENT_MONITOR_THREAD_ENABLE", "").strip().lower()
    if enabled not in ("1", "true", "on", "yes"):
        return

    from gevent import get_hub

    hub = get_hub()
    existing = getattr(hub, "periodic_monitoring_thread", None)
    if existing is not None:
        logging.getLogger("gunicorn.error").info(
            "post_worker_init [%s]: gevent monitor thread already running",
            worker_pid,
        )
        return

    monitor = hub.start_periodic_monitoring_thread()
    logging.getLogger("gunicorn.error").info(
        "post_worker_init [%s]: gevent monitor thread started (%s)",
        worker_pid,
        type(monitor).__name__ if monitor is not None else "None",
    )


def post_worker_init(worker):
    """Hooks that need a live gevent hub (after hub.reinit in GeventWorker)."""
    _log = logging.getLogger("gunicorn.error")
    try:
        _ensure_gevent_monitor(worker.pid)
    except Exception as exc:
        _log.warning(
            "post_worker_init [%s]: gevent monitor start failed: %s",
            worker.pid,
            exc,
        )
    try:
        _start_stall_watchdog(worker.pid)
    except Exception as exc:
        _log.warning(
            "post_worker_init [%s]: stall watchdog failed to start: %s",
            worker.pid,
            exc,
        )


_WORKER_EXIT_BUDGET_SECONDS = 2.0


def worker_exit(server, worker):
    """Drain PostHog without blocking the gevent hub.

    Complements :func:`app.lib.posthog_utils.register_posthog_atexit`. Recycle
    (``max_requests``) and SIGTERM both run this hook; it must return well
    inside gunicorn's 120s timeout or the arbiter SIGKILLs the worker and
    Render's /health check sees connection refused.
    """
    try:
        import faulthandler

        faulthandler.cancel_dump_traceback_later()
    except Exception:
        pass
    try:
        from app.lib.posthog_utils import (
            disarm_posthog_blocking_shutdown,
            shutdown_server_posthog,
        )

        # SDK atexit teardown (join/flush/shutdown) runs *after* this hook on
        # interpreter exit. Disarm it before our drain so recycle cannot hang
        # (PYTHON-FLASK-JD). GeventTimeout only covers cooperative drain;
        # it cannot interrupt OS Thread.join / Condition.wait — those APIs
        # must never be entered from the hub.
        disarm_posthog_blocking_shutdown()
        try:
            from gevent import Timeout as GeventTimeout
        except ImportError:
            GeventTimeout = None
        if GeventTimeout is not None:
            with GeventTimeout(_WORKER_EXIT_BUDGET_SECONDS, False):
                shutdown_server_posthog()
        else:
            shutdown_server_posthog()
    except Exception as exc:
        logging.getLogger("gunicorn.error").warning(
            "worker_exit [%s]: PostHog shutdown failed: %s", worker.pid, exc
        )


class _NoWinchFilter(logging.Filter):
    """Suppress the high-frequency SIGWINCH noise Replit emits on terminal resize."""

    def filter(self, record):
        return "winch" not in record.getMessage().lower()


logconfig_dict = {
    "version": 1,
    "disable_existing_loggers": False,
    "filters": {
        "no_winch": {"()": lambda: _NoWinchFilter()},
    },
    "formatters": {
        "generic": {
            "format": "%(asctime)s [%(process)d] [%(levelname)s] %(message)s",
            "datefmt": "[%Y-%m-%d %H:%M:%S %z]",
            "class": "logging.Formatter",
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stdout",
            "filters": ["no_winch"],
            "formatter": "generic",
        },
        "error_console": {
            "class": "logging.StreamHandler",
            "stream": "ext://sys.stderr",
            "filters": ["no_winch"],
            "formatter": "generic",
        },
    },
    "loggers": {
        "gunicorn.error": {
            "level": "INFO",
            "handlers": ["error_console"],
            "propagate": False,
        },
        "gunicorn.access": {
            "level": "INFO",
            "handlers": ["console"],
            "propagate": False,
        },
    },
    "root": {
        "level": "INFO",
        "handlers": ["console"],
    },
}
