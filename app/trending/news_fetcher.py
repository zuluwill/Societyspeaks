"""
News Fetcher Service

Fetches articles from curated news sources.
Supports: Guardian API (free), RSS feeds
"""

import os
import re
import logging
import requests
import feedparser
from datetime import datetime, timedelta
from typing import List, Dict, Optional
from flask import current_app

from app import db
from app.models import NewsSource, NewsArticle

logger = logging.getLogger(__name__)


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, preserving the text content."""
    if not text:
        return ""
    text = re.sub(r'<br\s*/?>', ' ', text)
    text = re.sub(r'<p\s*/?>', ' ', text)
    text = re.sub(r'</p>', ' ', text)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'&lt;', '<', text)
    text = re.sub(r'&gt;', '>', text)
    text = re.sub(r'&quot;', '"', text)
    text = re.sub(r'&#39;', "'", text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def clean_summary(text: str) -> Optional[str]:
    """
    Clean promotional content, ads, and credits from article/podcast summaries.
    Returns cleaned text or None if nothing meaningful remains.
    """
    if not text:
        return None
    
    text = strip_html_tags(text)
    
    original_text = text
    
    promo_patterns = [
        r'_{3,}.*',
        r'-{5,}.*',
        r'Get more from .+? with .+?\.',
        r'Enjoy bonus episodes.*?(?=\.|$)',
        r'Start your \d+-day free trial.*?(?=\.|$)',
        r'(?:powered|sponsored|brought to you) by .+?(?:\.|$)',
        r'(?:Get|Grab|Use) (?:our|the) exclusive .+? deal.*?(?=\.|$)',
        r'(?:NordVPN|ExpressVPN|Surfshark|VPN).*?(?:deal|offer|discount).*?(?=\.|$)',
        r'(?:Fuse|Revolut|Nord|Express).*?(?:sign up|free trial|bonus|discount).*?(?=\.|$)',
        r'To (?:sign up|save|get|claim).*?(?:visit|go to|head to).*?(?=\.|$)',
        r'It\'s risk-free with.*?guarantee.*?(?=\.|$)',
        r'Learn more about your ad choices.*',
        r'Visit podcastchoices\.com.*',
        r'See omnystudio\.com.*',
        r'(?:Social |Video |Assistant |Executive |Senior )?(?:Producer|Editor|Host|Writer|Director)s?:\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*(?:,\s*[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)* *',
        r'(?:Exec|Executive) Producer.*',
        r'(?:Presented|Hosted|Produced|Written|Directed) by.*',
        r'Subscribe to .+? (?:at|on|via).*',
        r'Follow us (?:on|at).*',
        r'Support (?:the show|us|this podcast).*',
        r'(?:Ad|Sponsor|Partner)(?:vertisement|ship)?s? by.*',
        r'This (?:episode|show|podcast) is (?:powered|sponsored|supported) by.*',
        r'[🎉🎧📧✅⚡️🔗💰🎁➼]',
    ]
    
    for pattern in promo_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.MULTILINE)
    
    text = re.sub(r'\s+', ' ', text)
    text = re.sub(r'\s*[,;]\s*[,;]+', ',', text)
    text = re.sub(r'[.!?]\s*[.!?]+', '.', text)
    text = text.strip(' .,;:-_')
    
    if len(text) < 50:
        return None
    
    if len(text) < len(original_text) * 0.3:
        return None
    
    return text[:2000] if len(text) > 2000 else text


class NewsFetcher:
    """Fetches news from curated sources."""
    
    def __init__(self):
        self.guardian_api_key = os.environ.get('GUARDIAN_API_KEY')
    
    def fetch_all_sources(self) -> List[NewsArticle]:
        """Fetch articles from all active sources."""
        try:
            sources = NewsSource.query.filter_by(is_active=True).all()
        except Exception as e:
            logger.error(f"Error fetching sources list: {e}")
            db.session.rollback()
            return []
        
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
                db.session.commit()
                
            except Exception as e:
                logger.error(f"Error fetching from {source.name}: {e}")
                db.session.rollback()
                try:
                    source = db.session.merge(source)
                    source.fetch_error_count += 1
                    db.session.commit()
                except Exception as inner_e:
                    logger.error(f"Error updating error count for {source.name}: {inner_e}")
                    db.session.rollback()
        
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
                
                try:
                    existing = NewsArticle.query.filter_by(
                        source_id=source.id,
                        external_id=external_id
                    ).first()
                    
                    if existing:
                        continue
                except Exception as db_err:
                    logger.warning(f"DB error checking existing article: {db_err}")
                    db.session.rollback()
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
            db.session.rollback()
            raise
        
        return articles
    
    def _fetch_rss(self, source: NewsSource) -> List[NewsArticle]:
        """Fetch from RSS feed."""
        articles = []
        
        try:
            feed = feedparser.parse(source.feed_url)
            
            for entry in feed.entries[:20]:
                external_id = entry.get('id') or entry.get('link', '')
                
                try:
                    existing = NewsArticle.query.filter_by(
                        source_id=source.id,
                        external_id=external_id[:500]
                    ).first()
                    
                    if existing:
                        continue
                except Exception as db_err:
                    logger.warning(f"DB error checking existing article: {db_err}")
                    db.session.rollback()
                    continue
                
                published_at = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    published_at = datetime(*entry.published_parsed[:6])
                
                raw_summary = entry.get('summary', '')
                cleaned_summary = clean_summary(raw_summary) if raw_summary else None
                
                article = NewsArticle(
                    source_id=source.id,
                    external_id=external_id[:500],
                    title=entry.get('title', '')[:500],
                    summary=cleaned_summary,
                    url=entry.get('link', '')[:1000],
                    published_at=published_at
                )
                
                db.session.add(article)
                articles.append(article)
            
            db.session.commit()
            logger.info(f"Fetched {len(articles)} new articles from {source.name}")
            
        except Exception as e:
            logger.error(f"RSS feed error for {source.name}: {e}")
            db.session.rollback()
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
            'name': 'Financial Times',
            'feed_url': 'https://www.ft.com/rss/home',
            'source_type': 'rss',
            'reputation_score': 0.9
        },
        {
            'name': 'The Economist',
            'feed_url': 'https://www.economist.com/the-world-this-week/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9
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
            'name': 'The News Agents',
            'feed_url': 'https://feeds.captivate.fm/the-news-agents/',
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
            'feed_url': 'https://feeds.megaphone.fm/AALT9618167458',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'All-In Podcast',
            'feed_url': 'https://allinchamathjason.libsyn.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'The Tim Ferriss Show',
            'feed_url': 'https://timferriss.libsyn.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.85
        },
        {
            'name': 'Diary of a CEO',
            'feed_url': 'https://feeds.megaphone.fm/thediaryofaceo',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'Modern Wisdom',
            'feed_url': 'https://feeds.megaphone.fm/SIXMSB5088139739',
            'source_type': 'rss',
            'reputation_score': 0.8
        },
        {
            'name': 'Stratechery',
            'feed_url': 'https://stratechery.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Center - tech/business analysis
        },
    ]
    
    try:
        for source_data in default_sources:
            existing = NewsSource.query.filter_by(name=source_data['name']).first()
            if not existing:
                source = NewsSource(**source_data)
                db.session.add(source)
                logger.info(f"Added default source: {source_data['name']}")
        
        db.session.commit()
    except Exception as e:
        logger.error(f"Error seeding default sources: {e}")
        db.session.rollback()
