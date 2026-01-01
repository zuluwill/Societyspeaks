"""
News Fetcher Service

Fetches articles from curated news sources.
Supports: Guardian API (free), RSS feeds
"""

import os
import logging
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from flask import current_app

from app import db
from app.models import NewsSource, NewsArticle

logger = logging.getLogger(__name__)


class NewsFetcher:
    """Fetches news from curated sources."""
    
    def __init__(self):
        self.guardian_api_key = os.environ.get('GUARDIAN_API_KEY')
    
    def fetch_all_sources(self) -> List[NewsArticle]:
        """Fetch articles from all active sources."""
        sources = NewsSource.query.filter_by(is_active=True).all()
        all_articles = []
        
        for source in sources:
            try:
                if source.source_type == 'guardian':
                    articles = self._fetch_guardian(source)
                elif source.source_type == 'rss':
                    articles = self._fetch_rss(source)
                else:
                    logger.warning(f"Unknown source type: {source.source_type}")
                    continue
                
                all_articles.extend(articles)
                source.last_fetched_at = datetime.utcnow()
                source.fetch_error_count = 0
                
            except Exception as e:
                logger.error(f"Error fetching from {source.name}: {e}")
                source.fetch_error_count += 1
        
        db.session.commit()
        return all_articles
    
    def _fetch_guardian(self, source: NewsSource) -> List[NewsArticle]:
        """Fetch from Guardian API."""
        if not self.guardian_api_key:
            logger.warning("GUARDIAN_API_KEY not set")
            return []
        
        articles = []
        
        try:
            response = requests.get(
                'https://content.guardianapis.com/search',
                params={
                    'api-key': self.guardian_api_key,
                    'show-fields': 'headline,trailText,shortUrl',
                    'page-size': 20,
                    'order-by': 'newest',
                    'from-date': (datetime.utcnow() - timedelta(hours=6)).strftime('%Y-%m-%d'),
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            for item in data.get('response', {}).get('results', []):
                external_id = item.get('id')
                
                existing = NewsArticle.query.filter_by(
                    source_id=source.id,
                    external_id=external_id
                ).first()
                
                if existing:
                    continue
                
                fields = item.get('fields', {})
                
                article = NewsArticle(
                    source_id=source.id,
                    external_id=external_id,
                    title=fields.get('headline', item.get('webTitle', '')),
                    summary=fields.get('trailText', ''),
                    url=item.get('webUrl', ''),
                    published_at=datetime.fromisoformat(
                        item.get('webPublicationDate', '').replace('Z', '+00:00')
                    ) if item.get('webPublicationDate') else None
                )
                
                db.session.add(article)
                articles.append(article)
            
            db.session.commit()
            logger.info(f"Fetched {len(articles)} new articles from Guardian")
            
        except Exception as e:
            logger.error(f"Guardian API error: {e}")
            raise
        
        return articles
    
    def _fetch_rss(self, source: NewsSource) -> List[NewsArticle]:
        """Fetch from RSS feed."""
        articles = []
        
        try:
            feed = feedparser.parse(source.feed_url)
            
            for entry in feed.entries[:20]:
                external_id = entry.get('id') or entry.get('link', '')
                
                existing = NewsArticle.query.filter_by(
                    source_id=source.id,
                    external_id=external_id[:500]
                ).first()
                
                if existing:
                    continue
                
                published_at = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime(*entry.published_parsed[:6])
                
                article = NewsArticle(
                    source_id=source.id,
                    external_id=external_id[:500],
                    title=entry.get('title', '')[:500],
                    summary=entry.get('summary', '')[:2000] if entry.get('summary') else None,
                    url=entry.get('link', '')[:1000],
                    published_at=published_at
                )
                
                db.session.add(article)
                articles.append(article)
            
            db.session.commit()
            logger.info(f"Fetched {len(articles)} new articles from {source.name}")
            
        except Exception as e:
            logger.error(f"RSS feed error for {source.name}: {e}")
            raise
        
        return articles


def seed_default_sources():
    """Add default trusted news sources."""
    default_sources = [
        {
            'name': 'The Guardian',
            'feed_url': 'https://content.guardianapis.com/search',
            'source_type': 'guardian',
            'reputation_score': 0.85
        },
        {
            'name': 'BBC News',
            'feed_url': 'http://feeds.bbci.co.uk/news/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'Reuters',
            'feed_url': 'https://www.reutersagency.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.95
        },
        {
            'name': 'Associated Press',
            'feed_url': 'https://rsshub.app/apnews/topics/apf-topnews',
            'source_type': 'rss',
            'reputation_score': 0.95
        },
        {
            'name': 'Financial Times',
            'feed_url': 'https://www.ft.com/rss/home',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'The Economist',
            'feed_url': 'https://www.economist.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'Politico',
            'feed_url': 'https://rss.politico.com/politics-news.xml',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'Politico EU',
            'feed_url': 'https://www.politico.eu/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'UnHerd',
            'feed_url': 'https://unherd.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75
        },
        {
            'name': 'The Atlantic',
            'feed_url': 'https://www.theatlantic.com/feed/all/',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'Foreign Affairs',
            'feed_url': 'https://www.foreignaffairs.com/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'Semafor',
            'feed_url': 'https://www.semafor.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'Bloomberg',
            'feed_url': 'https://feeds.bloomberg.com/markets/news.rss',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'TechCrunch',
            'feed_url': 'https://techcrunch.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75
        },
        {
            'name': 'Axios',
            'feed_url': 'https://api.axios.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'The Times',
            'feed_url': 'https://www.thetimes.co.uk/rss',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'The Telegraph',
            'feed_url': 'https://www.telegraph.co.uk/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'The Independent',
            'feed_url': 'https://www.independent.co.uk/rss',
            'source_type': 'rss',
            'reputation_score': 0.75
        },
        {
            'name': 'The New Yorker',
            'feed_url': 'https://www.newyorker.com/feed/everything',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'The Spectator',
            'feed_url': 'https://www.spectator.co.uk/feed',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'The News Agents',
            'feed_url': 'https://feeds.simplecast.com/Gr3nDCvY',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'The Rest Is Politics',
            'feed_url': 'https://feeds.acast.com/public/shows/the-rest-is-politics',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'Triggernometry',
            'feed_url': 'https://feeds.acast.com/public/shows/triggernometry',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'All-In Podcast',
            'feed_url': 'https://feeds.megaphone.fm/all-in-with-chamath-jason-sacks-friedberg',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'The Tim Ferriss Show',
            'feed_url': 'https://rss.art19.com/tim-ferriss-show',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'Diary of a CEO',
            'feed_url': 'https://feeds.simplecast.com/tFDHTGpU',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'Modern Wisdom',
            'feed_url': 'https://feeds.megaphone.fm/modern-wisdom',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
    ]
    
    for source_data in default_sources:
        existing = NewsSource.query.filter_by(name=source_data['name']).first()
        if not existing:
            source = NewsSource(**source_data)
            db.session.add(source)
            logger.info(f"Added default source: {source_data['name']}")
    
    db.session.commit()
