import logging

bind = "0.0.0.0:5000"
workers = 4
reuse_port = True
timeout = 600
worker_class = "sync"


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
