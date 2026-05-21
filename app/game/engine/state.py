"""Society state model."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict

from app.game.constants import STAT_ALL


def _clamp(value: int) -> int:
    return max(0, min(100, int(value)))


@dataclass
class SocietyState:
    prosperity: int = 50
    trust: int = 50
    fairness: int = 50
    stability: int = 50
    future: int = 50
    debt_stress: int = 35
    autonomy: int = 55
    fragility: int = 0

    def to_dict(self) -> Dict[str, int]:
        return {key: getattr(self, key) for key in STAT_ALL}

    @classmethod
    def from_dict(cls, data: Dict[str, int] | None) -> 'SocietyState':
        if not data:
            return cls()
        kwargs = {}
        for key in STAT_ALL:
            if key in data:
                kwargs[key] = _clamp(data[key])
        return cls(**kwargs)

    def apply_deltas(self, deltas: Dict[str, int]) -> Dict[str, int]:
        """Apply stat deltas; return applied deltas for UI."""
        applied: Dict[str, int] = {}
        for key, delta in (deltas or {}).items():
            if key not in STAT_ALL or delta == 0:
                continue
            before = getattr(self, key)
            after = _clamp(before + int(delta))
            setattr(self, key, after)
            applied[key] = after - before
        return applied

    def mood_level(self) -> int:
        """0–4 mood index for visual grid."""
        avg = (self.trust + self.stability + self.prosperity) / 3
        if avg >= 75:
            return 4
        if avg >= 60:
            return 3
        if avg >= 45:
            return 2
        if avg >= 30:
            return 1
        return 0
