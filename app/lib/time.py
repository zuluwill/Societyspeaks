"""
Time helpers shared across the application.
"""

from datetime import datetime, timezone


def utcnow_naive() -> datetime:
    """
    Return a naive UTC datetime.

    This preserves existing storage/comparison semantics in codepaths that
    currently expect naive UTC values, while avoiding datetime.utcnow().
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)
