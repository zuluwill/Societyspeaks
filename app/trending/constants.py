"""
Shared constants and utilities for the trending module.
"""

import re
import html

VALID_TOPICS = [
    'Healthcare', 'Environment', 'Education', 'Technology', 'Economy', 
    'Politics', 'Society', 'Infrastructure', 'Geopolitics', 'Business', 'Culture'
]

TARGET_AUDIENCE_DESCRIPTION = """
Our target audience follows podcasts like: The Rest is Politics, Newsagents, Triggernometry, 
All-In Podcast, UnHerd, Diary of a CEO, Modern Wisdom, Tim Ferriss Show, Louis Theroux.

They value:
- Nuanced political/policy discussion (not partisan culture war)
- Geopolitics and international affairs
- Technology, economics, and entrepreneurship
- Intellectual depth over sensationalism
- Contrarian or heterodox perspectives
- Long-form substantive debate
"""


def strip_html_tags(text: str) -> str:
    """Remove HTML tags and decode HTML entities from text."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p\s*/?>', ' ', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = html.unescape(text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()
