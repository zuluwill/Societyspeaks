"""Fetch podcast artwork URLs from RSS feeds."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import feedparser
import requests

FEEDS = {
    'Acquired Podcast': 'https://feeds.simplecast.com/JGE3yC0V',
    'All-In Podcast': 'https://allinchamathjason.libsyn.com/rss',
    'Huberman Lab': 'https://feeds.megaphone.fm/hubermanlab',
    'Lex Fridman Podcast': 'https://lexfridman.com/feed/podcast/',
    'Modern Wisdom': 'https://feeds.megaphone.fm/SIXMSB5088139739',
    'The Rest Is Politics': 'https://feeds.acast.com/public/shows/the-rest-is-politics',
    'The Tim Ferriss Show': 'https://timferriss.libsyn.com/rss',
}

for name, url in FEEDS.items():
    try:
        resp = requests.get(url, timeout=12, headers={'User-Agent': 'SocietySpeaks/1.0'})
        feed = feedparser.parse(resp.content)
        img = feed.feed.get('image', {}).get('href', '')
        itunes = feed.feed.get('itunes_image', {})
        itunes_href = itunes.get('href', '') if isinstance(itunes, dict) else ''
        logo = img or itunes_href
        print(f"{name}|||{logo}")
    except Exception as e:
        print(f"{name}|||ERROR:{e}")
