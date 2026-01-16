"""
Timezone Utilities

Handles timezone conversions with proper DST (Daylight Saving Time) support.
Prevents issues with ambiguous or non-existent times during DST transitions.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
import pytz

logger = logging.getLogger(__name__)


def get_next_scheduled_time(
    timezone_str: str,
    preferred_hour: int,
    preferred_minute: int = 0,
    from_time: Optional[datetime] = None
) -> datetime:
    """
    Calculate the next scheduled time in UTC, handling DST correctly.

    This function properly handles:
    - Non-existent times (spring forward): Moves to the next valid time
    - Ambiguous times (fall back): Uses the first occurrence (before DST ends)

    Args:
        timezone_str: Timezone string (e.g., 'America/New_York', 'Europe/London')
        preferred_hour: Hour of day (0-23) for scheduling
        preferred_minute: Minute of hour (0-59) for scheduling
        from_time: Starting point (defaults to now in the given timezone)

    Returns:
        datetime: Next scheduled time in UTC (timezone-naive)
    """
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{timezone_str}', falling back to UTC")
        tz = pytz.UTC

    # Get current time in the target timezone
    if from_time is None:
        local_now = datetime.now(tz)
    else:
        if from_time.tzinfo is None:
            local_now = tz.localize(from_time)
        else:
            local_now = from_time.astimezone(tz)

    # Create naive datetime for today at preferred time
    target_naive = local_now.replace(
        hour=preferred_hour,
        minute=preferred_minute,
        second=0,
        microsecond=0
    ).replace(tzinfo=None)

    # Try to localize it - this handles DST properly
    target_local = safe_localize(tz, target_naive)

    # If the time has passed, move to tomorrow
    if target_local <= local_now:
        tomorrow_naive = target_naive + timedelta(days=1)
        target_local = safe_localize(tz, tomorrow_naive)

    # Convert to UTC and remove tzinfo for storage
    target_utc = target_local.astimezone(pytz.UTC).replace(tzinfo=None)

    return target_utc


def get_weekly_scheduled_time(
    timezone_str: str,
    preferred_hour: int,
    preferred_weekday: int = 0,  # 0 = Monday
    preferred_minute: int = 0,
    from_time: Optional[datetime] = None
) -> datetime:
    """
    Calculate the next weekly scheduled time in UTC, handling DST correctly.

    Args:
        timezone_str: Timezone string (e.g., 'America/New_York')
        preferred_hour: Hour of day (0-23)
        preferred_weekday: Day of week (0=Monday, 6=Sunday)
        preferred_minute: Minute of hour (0-59)
        from_time: Starting point (defaults to now)

    Returns:
        datetime: Next scheduled time in UTC (timezone-naive)
    """
    try:
        tz = pytz.timezone(timezone_str)
    except pytz.UnknownTimeZoneError:
        logger.warning(f"Unknown timezone '{timezone_str}', falling back to UTC")
        tz = pytz.UTC

    # Get current time in the target timezone
    if from_time is None:
        local_now = datetime.now(tz)
    else:
        if from_time.tzinfo is None:
            local_now = tz.localize(from_time)
        else:
            local_now = from_time.astimezone(tz)

    # Calculate days until target weekday
    current_weekday = local_now.weekday()
    days_ahead = preferred_weekday - current_weekday

    if days_ahead < 0:  # Target day already happened this week
        days_ahead += 7
    elif days_ahead == 0:
        # Same day - check if time has passed
        target_time_today = local_now.replace(
            hour=preferred_hour,
            minute=preferred_minute,
            second=0,
            microsecond=0
        )
        if local_now >= target_time_today:
            days_ahead = 7  # Move to next week

    # Calculate target date
    target_date = local_now.date() + timedelta(days=days_ahead)

    # Create naive datetime
    target_naive = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        preferred_hour,
        preferred_minute,
        0
    )

    # Localize with DST handling
    target_local = safe_localize(tz, target_naive)

    # Convert to UTC
    target_utc = target_local.astimezone(pytz.UTC).replace(tzinfo=None)

    return target_utc


def safe_localize(tz: pytz.BaseTzInfo, naive_dt: datetime) -> datetime:
    """
    Safely localize a naive datetime, handling DST edge cases.

    - For non-existent times (during spring forward): Returns the time after the gap
    - For ambiguous times (during fall back): Returns the first occurrence (DST=True)

    Args:
        tz: pytz timezone object
        naive_dt: Naive datetime to localize

    Returns:
        Timezone-aware datetime
    """
    try:
        # Try to localize normally (is_dst=None raises exception for ambiguous/non-existent)
        return tz.localize(naive_dt, is_dst=None)
    except pytz.AmbiguousTimeError:
        # Time occurs twice (fall back) - use the first occurrence (still in DST)
        logger.debug(f"Ambiguous time {naive_dt} in {tz}, using DST=True")
        return tz.localize(naive_dt, is_dst=True)
    except pytz.NonExistentTimeError:
        # Time doesn't exist (spring forward) - move forward to valid time
        logger.debug(f"Non-existent time {naive_dt} in {tz}, normalizing")
        # Localize with is_dst=False and normalize to get correct time
        localized = tz.localize(naive_dt, is_dst=False)
        return tz.normalize(localized)


def is_valid_timezone(timezone_str: str) -> bool:
    """
    Check if a timezone string is valid.

    Args:
        timezone_str: Timezone string to validate

    Returns:
        True if valid, False otherwise
    """
    try:
        pytz.timezone(timezone_str)
        return True
    except pytz.UnknownTimeZoneError:
        return False


def get_common_timezones() -> list:
    """
    Get a list of common timezones for UI dropdowns.

    Returns:
        List of timezone strings
    """
    return [
        'UTC',
        'US/Eastern',
        'US/Central',
        'US/Mountain',
        'US/Pacific',
        'Europe/London',
        'Europe/Paris',
        'Europe/Berlin',
        'Europe/Amsterdam',
        'Asia/Tokyo',
        'Asia/Shanghai',
        'Asia/Singapore',
        'Asia/Dubai',
        'Australia/Sydney',
        'Australia/Melbourne',
        'Pacific/Auckland',
    ]
