import logging

bind = "0.0.0.0:5000"
workers = 4
reuse_port = True
timeout = 120
worker_class = "gevent"
worker_connections = 1000

# Load the application in the master process before forking workers.
# This ensures gevent's monkey.patch_all() (called at the top of run.py)
# executes before any worker or library imports ssl/socket/threading.
# Without this, gunicorn's own internals pull in urllib3 → ssl before each
# worker runs run.py, so gevent can't patch ssl and outbound HTTPS calls
# (Stripe, Resend, PostHog) block the worker during the network wait.
preload_app = True


def post_fork(server, worker):
    """Reset all inherited connection pools in each worker after forking.

    With preload_app=True the master process runs create_app() (via run.py)
    before forking, so Redis pools, the SQLAlchemy engine, and Flask-Caching's
    Redis client all exist before any worker is created.  After fork() the
    parent and child share the same socket file descriptors.  Using those
    sockets from multiple processes simultaneously corrupts protocol streams.

    This hook runs in each worker immediately after the fork, before the
    first request, and discards every inherited socket so the worker opens
    its own fresh connections on first use.
    """
    _log = logging.getLogger("gunicorn.error")

    # SQLAlchemy engine — dispose() closes all inherited DB connections so
    # the worker's connection pool starts empty and opens fresh sockets.
    try:
        from app import db
        db.engine.dispose()
        _log.debug("post_fork [%s]: SQLAlchemy engine disposed", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: SQLAlchemy engine dispose failed: %s", worker.pid, exc)

    # Session Redis — created in Config class body at module import time.
    try:
        from config import Config
        pool = getattr(getattr(Config, "SESSION_REDIS", None), "connection_pool", None)
        if pool is not None:
            pool.reset()
            _log.debug("post_fork [%s]: SESSION_REDIS pool reset", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: SESSION_REDIS pool reset failed: %s", worker.pid, exc)

    # Flask-Caching RedisCache — created inside create_app().
    try:
        from app import cache as _cache
        backend = getattr(_cache, "cache", None)
        pool = getattr(getattr(backend, "_client", None), "connection_pool", None)
        if pool is not None:
            pool.reset()
            _log.debug("post_fork [%s]: cache pool reset", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: cache pool reset failed: %s", worker.pid, exc)


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
