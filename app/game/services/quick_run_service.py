"""Quick Run pool — plan §3.2: replay anytime, curated, no streak credit.

The pool is built from the launch rotation minus *today's* scenario so a
Quick Run never collides with the daily ritual. Each entry carries the same
hub metadata as the daily so the picker can render category + teaser
consistently.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.game.engine.scenario import load_scenario
from app.game.services.daily_service import (
    LAUNCH_SCENARIO_ROTATION,
    scheduled_scenario_slug,
)


def quick_run_pool(*, exclude_today: bool = True) -> List[Dict[str, Any]]:
    """Return the curated Quick Run pool with title/category/teaser per entry."""
    today_slug = scheduled_scenario_slug() if exclude_today else None
    pool: List[Dict[str, Any]] = []
    for entry in LAUNCH_SCENARIO_ROTATION:
        slug = entry['slug']
        if today_slug and slug == today_slug:
            continue
        try:
            scenario = load_scenario(slug)
        except (FileNotFoundError, ValueError):
            continue
        pool.append(
            {
                'scenario_slug': slug,
                'title': scenario.get('title', slug),
                'subtitle': scenario.get('subtitle', ''),
                'category': entry.get('category', 'Daily'),
                'teaser': entry.get('teaser', ''),
                'total_turns': len(scenario.get('turns', [])),
            }
        )
    return pool


def is_quick_run_slug(slug: str) -> bool:
    """True when slug is one of the curated Quick Run scenarios."""
    return any(entry['slug'] == slug for entry in LAUNCH_SCENARIO_ROTATION)


def quick_run_entry(slug: str) -> Optional[Dict[str, Any]]:
    """Hub metadata for a single Quick Run scenario by slug."""
    for entry in quick_run_pool(exclude_today=False):
        if entry['scenario_slug'] == slug:
            return entry
    return None
