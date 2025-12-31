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
    ]
    
    for source_data in default_sources:
        existing = NewsSource.query.filter_by(name=source_data['name']).first()
        if not existing:
            source = NewsSource(**source_data)
            db.session.add(source)
            logger.info(f"Added default source: {source_data['name']}")
    
    db.session.commit()
