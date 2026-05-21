"""Procedural emblem from run seed."""

from __future__ import annotations

import hashlib
from typing import Dict, Tuple


def emblem_style(seed: str) -> Dict[str, str | int]:
    """Deterministic colours and shape index from seed."""
    digest = hashlib.sha256(seed.encode()).hexdigest()
    hue = int(digest[:2], 16) % 360
    shape = int(digest[2:3], 16) % 4
    accent = f'hsl({hue}, 55%, 58%)'
    accent_soft = f'hsla({hue}, 45%, 48%, 0.35)'
    return {
        'accent': accent,
        'accent_soft': accent_soft,
        'shape': shape,
    }
