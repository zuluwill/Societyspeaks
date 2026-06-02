"""Society-name suggestions for the Tradeoffs hub.

Suggestions are <= 48 chars (the input's maxlength) and deterministic when
handed a seeded ``random.Random``.
"""

from __future__ import annotations

import random
from typing import Any, List, Optional

_COINED = (
    'Verenmar', 'Astralis', 'Caldoria', 'Marivelle', 'Tiberon', 'Esmark',
    'Auronia', 'Solenne', 'Lindholm', 'Otavia', 'Velmara', 'Nyssara',
    'Calderon', 'Brightholm', 'Ashmere', 'Dunhaven', 'Evermoor', 'Galewyn',
    'Highmere', 'Ironvale', 'Larkspur', 'Meridon', 'Norhaven', 'Sundermere',
)

_ADJECTIVES = (
    'Verdant', 'Halcyon', 'Golden', 'Northern', 'Free', 'United', 'Bright',
    'Silver', 'Emerald', 'Azure', 'Highland', 'Granite', 'Amber', 'Open',
)

_POLITIES = (
    'Republic', 'Commonwealth', 'Federation', 'Union', 'Concord', 'Assembly',
    'Coalition', 'Confederation', 'Dominion', 'Accord',
)

_GEOFORMS = (
    'Reach', 'Vale', 'Expanse', 'Coast', 'Highlands', 'Frontier', 'Isles',
    'Marches', 'Heartland', 'Provinces', 'Basin', 'Plains',
)

_MAX_LEN = 48


def _one(rng: random.Random) -> str:
    pattern = rng.randint(0, 4)
    if pattern == 0:
        name = f'The {rng.choice(_ADJECTIVES)} {rng.choice(_POLITIES)}'
    elif pattern == 1:
        name = rng.choice(_COINED)
    elif pattern == 2:
        name = f'The {rng.choice(_ADJECTIVES)} {rng.choice(_GEOFORMS)}'
    elif pattern == 3:
        name = f'{rng.choice(_COINED)} {rng.choice(_POLITIES)}'
    else:
        name = f'New {rng.choice(_COINED)}'
    return name[:_MAX_LEN]


def generate_society_names(
    count: int = 8,
    *,
    rng: Optional[random.Random] = None,
    seed: Any = None,
) -> List[str]:
    """Return ``count`` distinct society-name suggestions.

    The first element is intended to be the pre-filled default; the rest feed
    the "roll another" affordance on the hub. Pass ``seed`` (any hashable) to
    make the output stable per caller — the hub uses this so a reload doesn't
    shuffle the visitor's pre-fill mid-decision.
    """
    if count < 1:
        return []
    if rng is None:
        rng = random.Random(seed) if seed is not None else random.Random()
    names: List[str] = []
    seen = set()
    for _ in range(count * 25):
        if len(names) >= count:
            break
        name = _one(rng)
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names


def generate_society_name(
    *,
    rng: Optional[random.Random] = None,
    seed: Any = None,
) -> str:
    """Return a single society-name suggestion."""
    return generate_society_names(1, rng=rng, seed=seed)[0]
