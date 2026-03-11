import logging

bind = "0.0.0.0:5000"


def post_fork(server, worker):
    """Reset all inherited Redis connection pools after forking.

    gunicorn forks workers from the master process.  run.py calls
    create_app() in the master, so Redis connection pools (session,
    cache) are open before any worker is forked.  After fork() the
    parent and child share the same socket file descriptors.  If two
    workers send commands on the same socket simultaneously they corrupt
    each other's Redis protocol stream — this surfaces much more readily
    under gevent's higher concurrency than with sync workers.

    ConnectionPool.reset() disconnects every inherited socket so the
    worker opens its own fresh connections on first use.
    """
    _log = logging.getLogger("gunicorn.error")

    # Session Redis — created in Config class body at module import time,
    # which is before create_app() and therefore before any fork.
    try:
        from config import Config
        pool = getattr(getattr(Config, "SESSION_REDIS", None), "connection_pool", None)
        if pool is not None:
            pool.reset()
            _log.debug("post_fork [%s]: SESSION_REDIS pool reset", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: SESSION_REDIS pool reset failed: %s", worker.pid, exc)

    # Flask-Caching RedisCache — created inside create_app() which is called
    # in run.py before gunicorn forks.  The backend client sits at cache.cache._client.
    try:
        from app import cache as _cache
        backend = getattr(_cache, "cache", None)
        pool = getattr(getattr(backend, "_client", None), "connection_pool", None)
        if pool is not None:
            pool.reset()
            _log.debug("post_fork [%s]: cache pool reset", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: cache pool reset failed: %s", worker.pid, exc)
workers = 4
reuse_port = True
timeout = 120
worker_class = "gevent"
worker_connections = 1000


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
