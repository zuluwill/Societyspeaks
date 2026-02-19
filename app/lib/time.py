"""
Time helpers shared across the application.

Single source of truth for "now in UTC" as a naive datetime (DB/comparison
compatibility). Use utcnow_naive() inline; for column defaults use the
callable: default=utcnow_naive, onupdate=utcnow_naive.
"""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """
    Return a naive UTC datetime.

    Use this instead of deprecated datetime.utcnow(). Preserves existing
    storage/comparison semantics for naive UTC values.
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
