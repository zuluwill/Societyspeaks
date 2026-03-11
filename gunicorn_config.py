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
    before forking, so every connection pool — SQLAlchemy, session Redis,
    Flask-Caching Redis — is open before any worker is created.  After fork()
    the parent and child share the same underlying socket file descriptors.
    Using those sockets from multiple processes simultaneously corrupts
    protocol streams (Redis) or libpq state (PostgreSQL).

    This hook runs in each worker immediately after the fork, before the
    first request is handled, and discards every inherited socket so the
    worker opens its own fresh connections on first use.

    Each reset is isolated in its own try/except so a failure in one does
    not prevent the others from running.
    """
    _log = logging.getLogger("gunicorn.error")

    def _reset_redis_pool(label, pool):
        """Disconnect all sockets in a Redis ConnectionPool.

        ConnectionPool.reset() closes every socket in the pool without
        waiting for in-flight commands.  The next command issued by this
        worker will open a fresh socket owned solely by this process.
        Logs at INFO so the reset is visible in production startup output.
        """
        if pool is None:
            _log.debug("post_fork [%s]: %s — no pool (Redis not configured)", worker.pid, label)
            return
        pool.reset()
        _log.info("post_fork [%s]: %s pool reset OK", worker.pid, label)

    # ------------------------------------------------------------------
    # 1. SQLAlchemy connection pool
    #    db.engine is a Flask-SQLAlchemy 3.x property that resolves through
    #    current_app, so it must be called inside an application context.
    #    We import the Flask app from run (the module gunicorn loaded via
    #    run:app) to build that context without re-running create_app().
    #    dispose() (close=True by default) actively closes inherited sockets.
    #    SQLAlchemy opens fresh ones on the next query in this worker.
    # ------------------------------------------------------------------
    try:
        from run import app as _flask_app
        from app import db as _db
        with _flask_app.app_context():
            _db.engine.dispose()
        _log.info("post_fork [%s]: SQLAlchemy engine disposed OK", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: SQLAlchemy engine dispose failed: %s", worker.pid, exc)

    # ------------------------------------------------------------------
    # 2. Session Redis pool
    #    Config.SESSION_REDIS is created at class-body execution time
    #    (before create_app()), so it is always pre-fork.
    # ------------------------------------------------------------------
    try:
        from config import Config
        pool = getattr(getattr(Config, "SESSION_REDIS", None), "connection_pool", None)
        _reset_redis_pool("SESSION_REDIS", pool)
    except Exception as exc:
        _log.warning("post_fork [%s]: SESSION_REDIS pool reset failed: %s", worker.pid, exc)

    # ------------------------------------------------------------------
    # 3. counter_utils lru_cache'd Redis client
    #    increment_counter() is only called during request handling so the
    #    lru_cache is normally empty at fork time and there is nothing to
    #    reset.  We clear it defensively so that if a warm-startup health
    #    check or future startup hook ever calls increment_counter(), any
    #    cached client with inherited sockets is discarded.
    # ------------------------------------------------------------------
    try:
        from app.lib.counter_utils import _get_redis_client as _counter_rc
        _counter_rc.cache_clear()
        _log.info("post_fork [%s]: counter_utils Redis client cache cleared", worker.pid)
    except Exception as exc:
        _log.warning("post_fork [%s]: counter_utils cache clear failed: %s", worker.pid, exc)

    # ------------------------------------------------------------------
    # 4. Flask-Caching Redis pool
    #    Flask-Caching's RedisCache backend exposes _read_client and
    #    _write_client.  In a single-server setup they are the same object
    #    sharing one ConnectionPool, so resetting either one covers both.
    #    This client is created inside create_app() which runs in the master
    #    with preload_app=True, so it is pre-fork.
    # ------------------------------------------------------------------
    try:
        from app import cache as _cache
        backend = getattr(_cache, "cache", None)
        # Prefer _write_client; fall back to _read_client for read-only configs.
        client = getattr(backend, "_write_client", None) or getattr(backend, "_read_client", None)
        pool = getattr(client, "connection_pool", None)
        _reset_redis_pool("Flask-Caching", pool)
    except Exception as exc:
        _log.warning("post_fork [%s]: Flask-Caching pool reset failed: %s", worker.pid, exc)


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
