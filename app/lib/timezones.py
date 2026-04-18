"""Shared timezone list for subscription preference dropdowns.

Single source of truth: register as a Jinja global in app/__init__.py so every
subscription form across Daily Question, Daily Brief, Journey Reminders, and
Paid Briefings uses the same list without duplication.
"""

COMMON_TIMEZONES = [
    ("Europe", [
        ("Europe/London", "London (GMT/BST)"),
        ("Europe/Paris", "Paris (CET/CEST)"),
        ("Europe/Berlin", "Berlin (CET/CEST)"),
        ("Europe/Amsterdam", "Amsterdam (CET/CEST)"),
        ("Europe/Zurich", "Zürich (CET/CEST)"),
        ("Europe/Stockholm", "Stockholm (CET/CEST)"),
        ("Europe/Warsaw", "Warsaw (CET/CEST)"),
        ("Europe/Istanbul", "Istanbul (TRT)"),
    ]),
    ("Americas", [
        ("America/New_York", "New York (EST/EDT)"),
        ("America/Chicago", "Chicago (CST/CDT)"),
        ("America/Denver", "Denver (MST/MDT)"),
        ("America/Los_Angeles", "Los Angeles (PST/PDT)"),
        ("America/Toronto", "Toronto (EST/EDT)"),
        ("America/Vancouver", "Vancouver (PST/PDT)"),
        ("America/Sao_Paulo", "São Paulo (BRT)"),
        ("America/Mexico_City", "Mexico City (CST/CDT)"),
    ]),
    ("Africa & Middle East", [
        ("Africa/Johannesburg", "Johannesburg (SAST)"),
        ("Asia/Dubai", "Dubai (GST)"),
    ]),
    ("Asia & Pacific", [
        ("Asia/Kolkata", "Mumbai / New Delhi (IST)"),
        ("Asia/Bangkok", "Bangkok (ICT)"),
        ("Asia/Singapore", "Singapore (SGT)"),
        ("Asia/Tokyo", "Tokyo (JST)"),
        ("Asia/Shanghai", "Shanghai / Beijing (CST)"),
        ("Asia/Jakarta", "Jakarta (WIB)"),
        ("Australia/Sydney", "Sydney (AEST/AEDT)"),
        ("Australia/Melbourne", "Melbourne (AEST/AEDT)"),
        ("Pacific/Auckland", "Auckland (NZST/NZDT)"),
    ]),
]
