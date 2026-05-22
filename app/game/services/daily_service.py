"""Daily scenario schedule — UTC calendar, hub metadata, buffer seeding."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from flask import current_app

from app import db
from app.game.engine.scenario import load_scenario, list_scenario_slugs
from app.models.game import GameDailySchedule

# Launch rotation (plan §10.2 order). Admin CMS can override via GameDailySchedule.
LAUNCH_SCENARIO_ROTATION: List[Dict[str, str]] = [
    {
        'slug': 'debt-inherited',
        'category': 'Fiscal crisis',
        'teaser': 'Borrowing, taxes, and the bills that come due.',
    },
    {
        'slug': 'housing-squeeze',
        'category': 'Housing',
        'teaser': 'Build, regulate, or let the market run — someone pays.',
    },
    {
        'slug': 'ai-takes-jobs',
        'category': 'Technology & labour',
        'teaser': 'Automation, retraining, and who owns the upside.',
    },
    {
        'slug': 'energy-price-shock',
        'category': 'Energy',
        'teaser': 'Heat, light, and the price of keeping both.',
    },
    {
        'slug': 'water-runs-dry',
        'category': 'Water & climate',
        'teaser': 'Rivers shrink. Cities thirst. Someone gets rationed.',
    },
    {
        'slug': 'climate-vs-growth',
        'category': 'Climate & economy',
        'teaser': 'Binding targets meet factory payrolls.',
    },
    {
        'slug': 'migration-pressures',
        'category': 'Migration',
        'teaser': 'Borders, asylum, and the capacity to absorb.',
    },
    {
        'slug': 'surveillance-dilemma',
        'category': 'Security & privacy',
        'teaser': 'Safety demands watching. Freedom demands limits.',
    },
    {
        'slug': 'young-vs-old',
        'category': 'Demographics',
        'teaser': 'Pensions, youth unemployment, and the generational contract.',
    },
    {
        'slug': 'tax-cuts-public-services',
        'category': 'Tax & services',
        'teaser': 'Campaign promises meet public arithmetic.',
    },
    {
        'slug': 'populist-surge',
        'category': 'Democratic stress',
        'teaser': 'The crowd wants simple answers. Reality refuses.',
    },
    {
        'slug': 'corruption-vs-stability',
        'category': 'Governance',
        'teaser': 'Scandal, inquiry, and the fear of what comes next.',
    },
    {
        'slug': 'brain-drain',
        'category': 'Talent & education',
        'teaser': 'Talent, migration, and who your country keeps.',
    },
    {
        'slug': 'currency-crisis',
        'category': 'Monetary crisis',
        'teaser': 'The exchange rate falls. Confidence follows.',
    },
]

DEFAULT_BUFFER_DAYS = 14


def utc_game_date(when: Optional[datetime] = None) -> date:
    """Player-facing 'today' for Tradeoffs (UTC-global per plan §3.1)."""
    dt = when or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.date()


def _teaser_for_slug(slug: str) -> str:
    for entry in LAUNCH_SCENARIO_ROTATION:
        if entry['slug'] == slug:
            return entry.get('teaser', '')
    return ''


def _rotation_entry(for_date: date) -> Dict[str, str]:
    order = _active_rotation()
    idx = for_date.toordinal() % len(order)
    return order[idx]


def _active_rotation() -> List[Dict[str, str]]:
    """Scenarios that exist on disk, preserving launch order."""
    available = set(list_scenario_slugs())
    entries = [e for e in LAUNCH_SCENARIO_ROTATION if e['slug'] in available]
    if entries:
        return entries
    slugs = list_scenario_slugs()
    if not slugs:
        raise RuntimeError('No game scenarios available')
    return [{'slug': slugs[0], 'category': 'Daily', 'teaser': ''}]


def scheduled_scenario_slug(for_date: Optional[date] = None) -> str:
    """Resolve scenario slug for a UTC date (DB row or cyclical fallback)."""
    day = for_date or utc_game_date()
    row = GameDailySchedule.query.filter_by(schedule_date=day).first()
    if row:
        return row.scenario_slug
    return _rotation_entry(day)['slug']


def daily_meta(for_date: Optional[date] = None) -> Dict[str, Any]:
    """Hub/play metadata for a scheduled day."""
    day = for_date or utc_game_date()
    row = GameDailySchedule.query.filter_by(schedule_date=day).first()
    if row:
        slug = row.scenario_slug
        category = row.category_label or 'Daily'
        teaser = _teaser_for_slug(slug)
    else:
        entry = _rotation_entry(day)
        slug = entry['slug']
        category = entry['category']
        teaser = entry.get('teaser', '')

    scenario = load_scenario(slug)
    publish_hour = int(current_app.config.get('GAME_DAILY_PUBLISH_HOUR_UTC', 7))
    return {
        'schedule_date': day,
        'scenario_slug': slug,
        'title': scenario.get('title', slug),
        'subtitle': scenario.get('subtitle', ''),
        'category': category,
        'teaser': teaser,
        'total_turns': len(scenario.get('turns', [])),
        'publish_hour_utc': publish_hour,
    }


def tomorrow_teaser() -> Dict[str, Any]:
    """Category-only preview for anticipation (plan §7 — no title spoiler)."""
    tomorrow = utc_game_date() + timedelta(days=1)
    meta = daily_meta(tomorrow)
    return {
        'schedule_date': tomorrow,
        'category': meta['category'],
        'publish_hour_utc': meta['publish_hour_utc'],
    }


def ensure_schedule_buffer(days: Optional[int] = None) -> int:
    """Idempotently seed upcoming schedule rows. Returns rows inserted.

    Uses a single max(schedule_date) query to decide whether seeding is needed;
    skips the per-day existence checks when the buffer is already healthy.
    """
    buffer = days or int(current_app.config.get('GAME_SCHEDULE_BUFFER_DAYS', DEFAULT_BUFFER_DAYS))
    today = utc_game_date()
    last_scheduled = (
        db.session.query(db.func.max(GameDailySchedule.schedule_date)).scalar()
    )
    target_last = today + timedelta(days=buffer - 1)
    if last_scheduled and last_scheduled >= target_last:
        return 0

    inserted = 0
    start_offset = 0
    if last_scheduled and last_scheduled >= today:
        start_offset = (last_scheduled - today).days + 1

    for offset in range(start_offset, buffer):
        day = today + timedelta(days=offset)
        if GameDailySchedule.query.filter_by(schedule_date=day).first():
            continue
        entry = _rotation_entry(day)
        db.session.add(
            GameDailySchedule(
                schedule_date=day,
                scenario_slug=entry['slug'],
                category_label=entry['category'],
            )
        )
        inserted += 1
    if inserted:
        db.session.commit()
    return inserted
