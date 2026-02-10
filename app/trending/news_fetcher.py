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
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


# Pre-compiled HTML tag patterns for performance
HTML_PATTERNS = [
    (re.compile(r'<br\s*/?>'), ' '),
    (re.compile(r'<p\s*/?>'), ' '),
    (re.compile(r'</p>'), ' '),
    (re.compile(r'<[^>]+>'), ''),
    (re.compile(r'&nbsp;'), ' '),
    (re.compile(r'&amp;'), '&'),
    (re.compile(r'&lt;'), '<'),
    (re.compile(r'&gt;'), '>'),
    (re.compile(r'&quot;'), '"'),
    (re.compile(r'&#39;'), "'"),
    (re.compile(r'\s+'), ' '),
]

# Pre-compiled promotional content patterns for performance
PROMO_PATTERNS = [
    re.compile(pattern, re.IGNORECASE | re.MULTILINE) for pattern in [
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
]

# Cleanup patterns (also pre-compiled)
CLEANUP_WHITESPACE = re.compile(r'\s+')
CLEANUP_PUNCTUATION_COMMA = re.compile(r'\s*[,;]\s*[,;]+')
CLEANUP_PUNCTUATION_PERIOD = re.compile(r'[.!?]\s*[.!?]+')


def strip_html_tags(text: str) -> str:
    """Remove HTML tags from text, preserving the text content."""
    if not text:
        return ""
    for pattern, replacement in HTML_PATTERNS:
        text = pattern.sub(replacement, text)
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
    
    # Apply pre-compiled promotional patterns
    for pattern in PROMO_PATTERNS:
        text = pattern.sub('', text)
    
    # Apply pre-compiled cleanup patterns
    text = CLEANUP_WHITESPACE.sub(' ', text)
    text = CLEANUP_PUNCTUATION_COMMA.sub(',', text)
    text = CLEANUP_PUNCTUATION_PERIOD.sub('.', text)
    text = text.strip(' .,;:-_')
    
    if len(text) < 50:
        logger.debug(f"Rejected summary: too short ({len(text)} chars after cleaning)")
        return None
    
    if len(text) < len(original_text) * 0.3:
        logger.debug(f"Rejected summary: too much content removed ({len(text)}/{len(original_text)} chars)")
        return None
    
    return text[:2000] if len(text) > 2000 else text


class NewsFetcher:
    """
    Fetches news from curated sources.
    
    Error Handling:
    - Each source is fetched independently; failures don't affect other sources
    - Failed sources increment fetch_error_count for monitoring
    - Sources with 5+ consecutive errors are auto-disabled
    - All errors are logged for debugging
    """
    
    MAX_CONSECUTIVE_ERRORS = 5  # Auto-disable sources after this many failures
    
    def __init__(self):
        self.guardian_api_key = os.environ.get('GUARDIAN_API_KEY')
    
    def _handle_fetch_error(self, source: NewsSource, error: Exception) -> None:
        """
        Handle a fetch error for a source (DRY utility method).
        
        - Logs the error
        - Increments fetch_error_count
        - Auto-disables source after MAX_CONSECUTIVE_ERRORS
        - Handles transaction rollback/commit
        """
        logger.error(f"Error fetching from {source.name}: {error}")
        db.session.rollback()
        
        try:
            source = db.session.merge(source)
            source.fetch_error_count = (source.fetch_error_count or 0) + 1
            
            # Auto-disable sources with too many consecutive errors
            if source.fetch_error_count >= self.MAX_CONSECUTIVE_ERRORS:
                logger.warning(
                    f"Auto-disabling {source.name} after {source.fetch_error_count} "
                    f"consecutive errors. Re-enable manually after fixing."
                )
                source.is_active = False
            
            db.session.commit()
        except Exception as inner_e:
            logger.error(f"Error updating error count for {source.name}: {inner_e}")
            db.session.rollback()
    
    def fetch_all_sources(self) -> List[NewsArticle]:
        """
        Fetch articles from all active sources.
        
        Each source is fetched independently - a failure in one source
        will NOT affect other sources. This ensures pipeline resilience.
        
        Returns:
            List of newly fetched NewsArticle instances
        """
        try:
            sources = NewsSource.query.filter_by(is_active=True).all()
        except Exception as e:
            logger.error(f"Error fetching sources list: {e}")
            db.session.rollback()
            return []
        
        all_articles = []
        successful_sources = 0
        failed_sources = 0
        
        logger.info(f"Starting fetch from {len(sources)} active sources")
        
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
                source.fetch_error_count = 0  # Reset on success
                db.session.commit()
                successful_sources += 1
                
            except Exception as e:
                failed_sources += 1
                self._handle_fetch_error(source, e)
        
        logger.info(
            f"Fetch complete: {len(all_articles)} articles from "
            f"{successful_sources} sources ({failed_sources} failed)"
        )
        
        return all_articles
    
    def check_source_health(self, source: NewsSource) -> dict:
        """
        Check if a source's RSS feed is accessible and valid.
        
        Args:
            source: NewsSource to check
            
        Returns:
            dict with status, message, and entry_count
        """
        try:
            if source.source_type == 'guardian':
                if not self.guardian_api_key:
                    return {'status': 'error', 'message': 'Guardian API key not configured', 'entry_count': 0}
                return {'status': 'ok', 'message': 'Guardian API configured', 'entry_count': None}
            
            response = requests.get(
                source.feed_url,
                timeout=10,
                headers={'User-Agent': 'SocietySpeaks/1.0 (Health Check)'}
            )
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if feed.bozo and not feed.entries:
                return {
                    'status': 'error',
                    'message': f'Malformed feed: {feed.bozo_exception}',
                    'entry_count': 0
                }
            
            return {
                'status': 'ok',
                'message': 'Feed accessible and valid',
                'entry_count': len(feed.entries)
            }
            
        except requests.exceptions.Timeout:
            return {'status': 'error', 'message': 'Timeout', 'entry_count': 0}
        except requests.exceptions.RequestException as e:
            return {'status': 'error', 'message': str(e), 'entry_count': 0}
        except Exception as e:
            return {'status': 'error', 'message': str(e), 'entry_count': 0}
    
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
            
            try:
                db.session.commit()
                logger.info(f"Fetched {len(articles)} new articles from Guardian")
            except IntegrityError as e:
                # Handle race condition where another process inserted the same article
                db.session.rollback()
                logger.warning(f"Guardian: Duplicate article detected, retrying one by one: {e}")
                # Retry adding articles one by one to save what we can
                saved_articles = []
                for article in articles:
                    try:
                        existing = NewsArticle.query.filter_by(
                            source_id=article.source_id,
                            external_id=article.external_id
                        ).first()
                        if not existing:
                            db.session.add(article)
                            db.session.commit()
                            saved_articles.append(article)
                    except IntegrityError:
                        db.session.rollback()
                        continue
                logger.info(f"Guardian: Saved {len(saved_articles)} articles after retry")
                articles = saved_articles
            
        except Exception as e:
            logger.error(f"Guardian API error: {e}")
            db.session.rollback()
            raise
        
        return articles
    
    def _fetch_rss(self, source: NewsSource) -> List[NewsArticle]:
        """
        Fetch from RSS feed with proper error handling.
        
        Uses requests with timeout for network resilience,
        then parses with feedparser. Handles malformed feeds gracefully.
        """
        articles = []
        
        try:
            # Validate URL format
            if not source.feed_url or not source.feed_url.startswith(('http://', 'https://')):
                logger.warning(f"Invalid feed URL for {source.name}: {source.feed_url}")
                return []
            
            # Fetch with timeout using requests for better control
            try:
                response = requests.get(
                    source.feed_url,
                    timeout=15,  # 15 second timeout
                    headers={
                        'User-Agent': 'SocietySpeaks/1.0 (News Aggregator; +https://societyspeaks.io)'
                    }
                )
                response.raise_for_status()
                feed_content = response.content
            except requests.exceptions.Timeout:
                logger.warning(f"Timeout fetching RSS from {source.name} ({source.feed_url})")
                return []
            except requests.exceptions.RequestException as req_err:
                logger.warning(f"HTTP error fetching {source.name}: {req_err}")
                return []
            
            # Validate content type before parsing (catches JSON APIs, HTML error pages, etc.)
            content_type = response.headers.get('Content-Type', '').lower()
            valid_feed_types = ('xml', 'rss', 'atom', 'text/plain', 'application/octet-stream')
            if not any(t in content_type for t in valid_feed_types):
                # Some feeds don't set proper content-type, so also check if content looks like XML
                content_preview = feed_content[:500].decode('utf-8', errors='ignore').strip()
                if not content_preview.startswith(('<?xml', '<rss', '<feed', '<')):
                    logger.warning(f"Unexpected content type for {source.name}: {content_type}")
                    return []
            
            # Parse the feed content
            feed = feedparser.parse(feed_content)
            
            # Check for feed parsing errors (bozo flag)
            if feed.bozo and not feed.entries:
                logger.warning(f"Malformed feed from {source.name}: {feed.bozo_exception}")
                return []
            elif feed.bozo:
                # Feed has issues but still has entries - log warning but continue
                logger.debug(f"Feed {source.name} has minor issues: {feed.bozo_exception}")
            
            # Check if feed has any entries
            if not feed.entries:
                logger.info(f"No entries found in feed for {source.name}")
                return []
            
            for entry in feed.entries[:20]:
                external_id = entry.get('id') or entry.get('link', '')
                
                if not external_id:
                    continue  # Skip entries without any identifier
                
                try:
                    existing = NewsArticle.query.filter_by(
                        source_id=source.id,
                        external_id=external_id[:500]
                    ).first()
                    
                    if existing:
                        continue
                    
                    url = entry.get('link', '')
                    if url and NewsArticle.query.filter_by(url=url[:1000]).first():
                        continue
                except Exception as db_err:
                    logger.warning(f"DB error checking existing article: {db_err}")
                    db.session.rollback()
                    continue
                
                # Parse publication date with fallback
                published_at = None
                if hasattr(entry, 'published_parsed') and entry.published_parsed:
                    try:
                        published_at = datetime(*entry.published_parsed[:6])
                    except (ValueError, TypeError):
                        pass  # Invalid date, leave as None
                elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                    try:
                        published_at = datetime(*entry.updated_parsed[:6])
                    except (ValueError, TypeError):
                        pass
                
                # Get and clean summary
                raw_summary = entry.get('summary', '') or entry.get('description', '')
                cleaned_summary = clean_summary(raw_summary) if raw_summary else None
                
                # Get title with fallback
                title = entry.get('title', '')
                if not title:
                    continue  # Skip entries without titles
                
                # Get URL with validation
                url = entry.get('link', '')
                if not url or not url.startswith(('http://', 'https://')):
                    continue  # Skip entries without valid URLs
                
                article = NewsArticle(
                    source_id=source.id,
                    external_id=external_id[:500],
                    title=title[:500],
                    summary=cleaned_summary,
                    url=url[:1000],
                    published_at=published_at
                )
                
                db.session.add(article)
                articles.append(article)
            
            try:
                db.session.commit()
                logger.info(f"Fetched {len(articles)} new articles from {source.name}")
            except IntegrityError as e:
                # Handle race condition where another process inserted the same article
                db.session.rollback()
                logger.warning(f"{source.name}: Duplicate article detected, retrying one by one: {e}")
                # Retry adding articles one by one to save what we can
                saved_count = 0
                for article in articles:
                    try:
                        existing = NewsArticle.query.filter_by(
                            source_id=article.source_id,
                            external_id=article.external_id
                        ).first()
                        if not existing:
                            db.session.add(article)
                            db.session.commit()
                            saved_count += 1
                    except IntegrityError:
                        db.session.rollback()
                        continue
                logger.info(f"{source.name}: Saved {saved_count} articles after retry")
                articles = articles[:saved_count]
            
        except Exception as e:
            logger.error(f"RSS feed error for {source.name}: {e}")
            db.session.rollback()
            raise
        
        return articles


def seed_default_sources():
    """
    Add or update default trusted news sources.
    
    Updates existing sources with new field values (country, political_leaning, etc.)
    to ensure consistency across the database.
    """
    default_sources = [
        # ==========================================================================
        # CENTRE-LEFT SOURCES
        # ==========================================================================
        {
            'name': 'The Guardian',
            'feed_url': 'https://content.guardianapis.com/search',
            'source_type': 'guardian',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': -2.0  # Left (moved from Lean Left per AllSides chart v11)
        },
        {
            'name': 'The Atlantic',
            'feed_url': 'https://www.theatlantic.com/feed/all/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -2.0  # Left per AllSides
        },
        {
            'name': 'The Independent',
            'feed_url': 'https://www.independent.co.uk/rss',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United Kingdom',
            'political_leaning': -2.0  # Left per AllSides
        },
        {
            'name': 'The New Yorker',
            'feed_url': 'https://www.newyorker.com/feed/everything',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -2.0  # Left
        },
        {
            'name': 'Vox',
            'feed_url': 'https://www.vox.com/rss/index.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -2.0  # Left per AllSides
        },
        {
            'name': 'New Statesman',
            'feed_url': 'https://www.newstatesman.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': -2.0  # Left - British progressive
        },
        {
            'name': 'The Observer',
            'feed_url': 'https://www.theguardian.com/theobserver/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': -2.0  # Left - UK Sunday paper, Guardian sibling
        },
        {
            'name': 'The Intercept',
            'feed_url': 'https://theintercept.com/feed/?rss',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': -2.0  # Left - investigative journalism
        },
        {
            'name': 'ProPublica',
            'feed_url': 'https://www.propublica.org/feeds/propublica/main',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -1.0  # Centre-Left - investigative, non-profit
        },
        {
            'name': 'Slow Boring',
            'feed_url': 'https://www.slowboring.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -1.0  # Centre-Left - Matt Yglesias policy analysis
        },
        {
            'name': 'Noahpinion',
            'feed_url': 'https://www.noahpinion.blog/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -1.0  # Centre-Left - Noah Smith economics
        },
        {
            'name': 'Commonweal',
            'feed_url': 'https://www.commonwealmagazine.org/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -1.0  # Centre-Left - Catholic intellectual, social justice
        },
        {
            'name': 'Matt Taibbi',
            'feed_url': 'https://www.racket.news/feed',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': -2.0  # Left - heterodox, anti-establishment
        },
        {
            'name': 'Freddie deBoer',
            'feed_url': 'https://freddiedeboer.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': -2.0  # Left - education, mental health, socialist
        },
        {
            'name': 'Yascha Mounk',
            'feed_url': 'https://yaschamounk.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -0.5  # Lean Left - Persuasion, big ideas
        },
        {
            'name': 'Ezra Klein',
            'feed_url': 'https://ezraklein.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left - policy analysis
        },
        {
            'name': 'Anne Applebaum',
            'feed_url': 'https://anneapplebaum.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -0.5  # Lean Left - democracy, foreign affairs
        },
        {
            'name': 'Jonathan Rauch',
            'feed_url': 'https://jrauch.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -0.5  # Lean Left - liberalism, institutions
        },
        {
            'name': 'Zeynep Tufekci',
            'feed_url': 'https://zeynep.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -0.5  # Lean Left - tech, society, science (now NYT columnist)
        },
        {
            'name': 'Francis Fukuyama',
            'feed_url': 'https://francisfukuyama.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - democracy, development
        },
        
        # ==========================================================================
        # CENTRE SOURCES
        # ==========================================================================
        {
            'name': 'BBC News',
            'feed_url': 'http://feeds.bbci.co.uk/news/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre
        },
        {
            'name': 'BBC World Service',
            'feed_url': 'https://feeds.bbci.co.uk/news/world/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - global news service
        },
        {
            'name': 'Politico',
            'feed_url': 'https://rss.politico.com/politics-news.xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left per AllSides
        },
        {
            'name': 'Euractiv',
            'feed_url': 'https://www.euractiv.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'Belgium',
            'political_leaning': 0  # Centre - EU policy news
        },
        {
            'name': 'Carnegie Endowment',
            'feed_url': 'https://carnegieendowment.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'International Crisis Group',
            'feed_url': 'https://www.crisisgroup.org/rss-0',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'World Economic Forum',
            'feed_url': 'https://www.weforum.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'International',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'UN News',
            'feed_url': 'https://news.un.org/en/rss-feeds',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': 0  # Centre - UN official news
        },
        {
            'name': 'IEA',
            'feed_url': 'https://www.iea.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': 0  # Centre - energy policy, data-driven
        },
        {
            'name': 'WHO',
            'feed_url': 'https://www.who.int/news-room/rss',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'International',
            'political_leaning': 0  # Centre - global health organization
        },
        {
            'name': 'Chartbook',
            'feed_url': 'https://adamtooze.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -0.5  # Lean Left - Adam Tooze economics, geopolitics
        },
        {
            'name': 'Ian Bremmer',
            'feed_url': 'https://www.gzeromedia.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - geopolitical analysis, Eurasia Group
        },
        {
            'name': 'Financial Times',
            'feed_url': 'https://www.ft.com/rss/home',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre
        },
        {
            'name': 'The Economist',
            'feed_url': 'https://www.economist.com/the-world-this-week/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre (classical liberal)
        },
        {
            'name': 'Politico EU',
            'feed_url': 'https://www.politico.eu/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'Belgium',
            'political_leaning': 0  # Centre
        },
        {
            'name': 'Foreign Affairs',
            'feed_url': 'https://www.foreignaffairs.com/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - academic foreign policy
        },
        {
            'name': 'Bloomberg',
            'feed_url': 'https://feeds.bloomberg.com/markets/news.rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - business news
        },
        {
            'name': 'Axios',
            'feed_url': 'https://api.axios.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 0  # Centre
        },
        {
            'name': 'TechCrunch',
            'feed_url': 'https://techcrunch.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 0  # Centre - tech news
        },
        {
            'name': 'Stratechery',
            'feed_url': 'https://stratechery.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - tech/business analysis
        },
        {
            'name': 'Platformer',
            'feed_url': 'https://platformer.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - Casey Newton, Silicon Valley & democracy
        },
        {
            'name': 'Not Boring',
            'feed_url': 'https://notboring.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - Packy McCormick, tech strategy
        },
        {
            'name': 'The Pragmatic Engineer',
            'feed_url': 'https://blog.pragmaticengineer.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - Gergely Orosz, Big Tech & startups
        },
        {
            'name': 'Simon Willison',
            'feed_url': 'https://simonwillison.net/atom/everything/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - tech, programming, data
        },
        {
            'name': 'Paul Graham',
            'feed_url': 'https://anonyonoor.com/feeds/paul-graham',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - essays on startups, programming, life
        },
        {
            'name': 'Cory Doctorow',
            'feed_url': 'https://pluralistic.net/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left - tech, politics, culture
        },
        {
            'name': 'Farnam Street',
            'feed_url': 'https://fs.blog/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - wisdom/mental models
        },
        {
            'name': 'Semafor',
            'feed_url': 'https://www.semafor.com/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left per AllSides
        },
        {
            'name': 'Rest of World',
            'feed_url': 'https://restofworld.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 0  # Centre - international tech/society
        },
        {
            'name': 'The Conversation',
            'feed_url': 'https://theconversation.com/articles.atom',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - academic experts
        },
        {
            'name': 'Al Jazeera English',
            'feed_url': 'https://www.aljazeera.com/xml/rss/all.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'Qatar',
            'political_leaning': 0  # Centre - non-Western global perspective
        },
        {
            'name': 'Lawfare',
            'feed_url': 'https://www.lawfaremedia.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - legal/national security analysis
        },
        {
            'name': 'Foreign Policy',
            'feed_url': 'https://foreignpolicy.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - international affairs
        },
        {
            'name': 'War on the Rocks',
            'feed_url': 'https://warontherocks.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - defense/security analysis
        },
        {
            'name': 'MIT Technology Review',
            'feed_url': 'https://www.technologyreview.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - AI, biotech, climate tech
        },
        {
            'name': 'Carbon Brief',
            'feed_url': 'https://www.carbonbrief.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'South China Morning Post',
            'feed_url': 'https://www.scmp.com/rss/4/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'Hong Kong',
            'political_leaning': 0  # Centre - Asia/China coverage (China News feed)
        },
        {
            'name': 'Spiegel International',
            'feed_url': 'https://www.spiegel.de/international/index.rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Germany',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'Deutsche Welle',
            'feed_url': 'https://rss.dw.com/rdf/rss-en-all',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'Germany',
            'political_leaning': 0  # Centre per AllSides - German public broadcaster
        },
        {
            'name': 'Le Monde English',
            'feed_url': 'https://www.lemonde.fr/en/international/rss_full.xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'France',
            'political_leaning': -0.5  # Lean Left - French newspaper, English edition
        },
        {
            'name': 'France24',
            'feed_url': 'https://www.france24.com/en/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'France',
            'political_leaning': 0  # Centre - French international news
        },
        {
            'name': 'El País English',
            'feed_url': 'https://english.elpais.com/rss/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Spain',
            'political_leaning': -0.5  # Lean Left - Spanish newspaper, English edition
        },
        {
            'name': 'Nikkei Asia',
            'feed_url': 'https://asia.nikkei.com/rss/feed/nar',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Japan',
            'political_leaning': 0.5  # Right-Center per MBFC
        },
        {
            'name': 'Caixin Global',
            'feed_url': 'https://www.caixinglobal.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'China',
            'political_leaning': 0  # Centre - Chinese business news, English edition
        },
        {
            'name': 'Sixth Tone',
            'feed_url': 'https://www.sixthtone.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'China',
            'political_leaning': 0  # Centre - China-focused news, English by design
        },
        {
            'name': 'Channel NewsAsia',
            'feed_url': 'https://www.channelnewsasia.com/api/v1/rss-outbound-feed?_format=xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Singapore',
            'political_leaning': 0  # Centre - Singapore-based Asian news
        },
        {
            'name': 'Straits Times',
            'feed_url': 'https://www.straitstimes.com/news/singapore/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Singapore',
            'political_leaning': 0.5  # Right-Center per MBFC (pro-government)
        },
        {
            'name': 'Haaretz',
            'feed_url': 'https://www.haaretz.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Israel',
            'political_leaning': -1.0  # Lean Left per AllSides - Israeli newspaper
        },
        {
            'name': 'The National',
            'feed_url': 'https://www.thenationalnews.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Arab Emirates',
            'political_leaning': 0  # Centre - UAE newspaper, English by design
        },
        {
            'name': 'Al Monitor',
            'feed_url': 'https://www.al-monitor.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'Africa Confidential',
            'feed_url': 'https://www.africa-confidential.com/rss.aspx',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'International',
            'political_leaning': 0  # Centre - African political news
        },
        {
            'name': 'Mail & Guardian',
            'feed_url': 'http://mg.co.za/rss/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'South Africa',
            'political_leaning': -2.0  # Left per MBFC
        },
        {
            'name': 'Daily Maverick',
            'feed_url': 'https://www.dailymaverick.co.za/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'South Africa',
            'political_leaning': 0  # Least Biased per MBFC
        },
        {
            'name': 'AllAfrica',
            'feed_url': 'https://allafrica.com/tools/headlines/rdf/latest/headlines.rdf',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'International',
            'political_leaning': 0  # Centre - African news aggregation
        },
        {
            'name': 'Americas Quarterly',
            'feed_url': 'https://www.americasquarterly.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - Latin America analysis
        },
        {
            'name': 'El País América',
            'feed_url': 'https://english.elpais.com/news/america/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Spain',
            'political_leaning': -0.5  # Lean Left - El País, Americas edition
        },
        {
            'name': 'Ars Technica',
            'feed_url': 'https://feeds.arstechnica.com/arstechnica/index',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - deep tech analysis
        },
        {
            'name': 'Brookings Institution',
            'feed_url': 'https://www.brookings.edu/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - think tank, research-backed
        },
        {
            'name': 'Institute for Government',
            'feed_url': 'https://www.instituteforgovernment.org.uk/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - UK government effectiveness think tank
        },
        {
            'name': 'Institute for Fiscal Studies',
            'feed_url': 'https://feeds.acast.com/public/shows/5ea004d9fbcc383829c71657',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - UK fiscal policy research
        },
        {
            'name': 'Resolution Foundation',
            'feed_url': 'https://www.resolutionfoundation.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - UK living standards think tank
        },
        {
            'name': 'UK Parliament',
            'feed_url': 'https://bills.parliament.uk/rss/allbills.rss',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - official parliamentary proceedings
        },
        {
            'name': 'RAND Corporation',
            'feed_url': 'https://www.rand.org/pubs/new.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - policy research, objective analysis
        },
        {
            'name': 'Chatham House',
            'feed_url': 'https://www.chathamhouse.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - international affairs think tank
        },
        {
            'name': 'CSIS',
            'feed_url': 'https://www.csis.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - Center for Strategic and International Studies
        },
        {
            'name': 'OECD',
            'feed_url': 'https://www.oecd.org/newsroom/index.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': 0  # Centre - economic policy, international cooperation
        },
        {
            'name': 'World Bank',
            'feed_url': 'https://blogs.worldbank.org/en/blogs',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': 0  # Centre - development economics, global poverty
        },
        {
            'name': 'IMF',
            'feed_url': 'https://www.imf.org/en/rss-list',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'International',
            'political_leaning': 0  # Centre - monetary policy, global finance
        },
        {
            'name': 'Office for National Statistics',
            'feed_url': 'https://ons.gov.uk/releasecalendar',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - official UK statistics
        },
        {
            'name': 'Office for Budget Responsibility',
            'feed_url': 'https://obr.uk/feed',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - UK fiscal forecasts
        },
        {
            'name': 'Pew Research Center',
            'feed_url': 'https://www.pewresearch.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0  # Centre - nonpartisan fact tank
        },
        {
            'name': 'Our World in Data',
            'feed_url': 'https://ourworldindata.org/atom.xml',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'International',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'Eurostat',
            'feed_url': 'https://ec.europa.eu/eurostat/api/dissemination/catalogue/rss/en/statistics-update.rss',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'European Union',
            'political_leaning': 0  # Centre - official EU statistics
        },
        {
            'name': 'US Census Bureau',
            'feed_url': 'https://www.census.gov/newsroom/press-releases/by-year.xml',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United States',
            'political_leaning': 0  # Centre - official US demographic and economic data
        },
        {
            'name': 'Nieman Lab',
            'feed_url': 'https://www.niemanlab.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - future of journalism
        },
        {
            'name': 'Columbia Journalism Review',
            'feed_url': 'https://www.cjr.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - media criticism and analysis
        },
        {
            'name': 'Poynter',
            'feed_url': 'https://www.poynter.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - journalism education and ethics
        },
        
        # ==========================================================================
        # CENTRE-RIGHT SOURCES
        # ==========================================================================
        {
            'name': 'UnHerd',
            'feed_url': 'https://unherd.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United Kingdom',
            'political_leaning': 0.5  # Center (slight right) per AllSides
        },
        {
            'name': 'The Telegraph',
            'feed_url': 'https://www.telegraph.co.uk/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': 2.0  # Right per AllSides
        },
        {
            'name': 'The Dispatch',
            'feed_url': 'https://thedispatch.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - fact-based conservative
        },
        {
            'name': 'The Spectator',
            'feed_url': 'https://www.spectator.co.uk/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': 2.0  # Right per AllSides - British conservative magazine
        },
        {
            'name': 'The Times',
            'feed_url': 'https://www.thetimes.co.uk/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 1.0  # Lean Right - UK broadsheet
        },
        {
            'name': 'Reason',
            'feed_url': 'https://reason.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right per AllSides - libertarian
        },
        {
            'name': 'The Free Press',
            'feed_url': 'https://www.thefp.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - heterodox journalism
        },
        {
            'name': 'The Critic',
            'feed_url': 'https://thecritic.co.uk/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United Kingdom',
            'political_leaning': 1.5  # Right per MBFC
        },
        {
            'name': 'Marginal Revolution',
            'feed_url': 'https://feeds.feedburner.com/marginalrevolution/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - Tyler Cowen economics, libertarian-leaning
        },
        {
            'name': 'Cato Institute',
            'feed_url': 'https://www.cato.org/blog/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right per AllSides - libertarian think tank
        },
        {
            'name': 'Manhattan Institute',
            'feed_url': 'https://www.manhattan-institute.org/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 2.0  # Right - pairs with City Journal
        },
        {
            'name': 'Andrew Sullivan',
            'feed_url': 'https://andrewsullivan.substack.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - heterodox conservative
        },
        
        # ==========================================================================
        # RIGHT SOURCES
        # ==========================================================================
        {
            'name': 'National Review',
            'feed_url': 'https://www.nationalreview.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 2.0  # Right per AllSides - traditional conservative
        },
        {
            'name': 'The American Conservative',
            'feed_url': 'https://www.theamericanconservative.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 2.0  # Right per AllSides - paleoconservative
        },
        {
            'name': 'City Journal',
            'feed_url': 'https://www.city-journal.org/rss',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 2.0  # Right - urban policy conservative
        },
        {
            'name': 'The Commentary Magazine',
            'feed_url': 'https://www.commentary.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 2.0  # Right - neoconservative
        },
        {
            'name': 'First Things',
            'feed_url': 'https://www.firstthings.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 2.0  # Right - religious conservative intellectual
        },
        {
            'name': 'Christianity Today',
            'feed_url': 'https://www.christianitytoday.com/ct/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 1.0  # Right-Center per MBFC - evangelical
        },
        
        # ==========================================================================
        # PODCASTS (Assessed based on content and hosts)
        # ==========================================================================
        {
            'name': 'The News Agents',
            'feed_url': 'https://feeds.captivate.fm/the-news-agents/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': -2.0  # Left - UK political podcast
        },
        {
            'name': 'The Rest Is Politics',
            'feed_url': 'https://feeds.acast.com/public/shows/the-rest-is-politics',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - left and right hosts
        },
        {
            'name': 'Triggernometry',
            'feed_url': 'https://feeds.megaphone.fm/AALT9618167458',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': 1.0  # Centre-Right - libertarian/classical liberal
        },
        {
            'name': 'All-In Podcast',
            'feed_url': 'https://allinchamathjason.libsyn.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - tech/business, libertarian lean
        },
        {
            'name': 'The Tim Ferriss Show',
            'feed_url': 'https://timferriss.libsyn.com/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - lifestyle/business, apolitical
        },
        {
            'name': 'Diary of a CEO',
            'feed_url': 'https://feeds.megaphone.fm/thediaryofaceo',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - business/entrepreneurship, apolitical
        },
        {
            'name': 'Modern Wisdom',
            'feed_url': 'https://feeds.megaphone.fm/SIXMSB5088139739',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United Kingdom',
            'political_leaning': 0  # Centre - philosophy/lifestyle, apolitical
        },
        {
            'name': 'Acquired Podcast',
            'feed_url': 'https://feeds.simplecast.com/JGE3yC0V',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0  # Centre - business deep dives, apolitical
        },

        # ==========================================================================
        # ADDITIONAL RIGHT-LEANING SOURCES (for coverage balance)
        # Added to ensure better L/C/R balance in Daily Brief
        # ==========================================================================
        {
            'name': 'National Review',
            'feed_url': 'https://www.nationalreview.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 1.5  # Right per AllSides - conservative magazine
        },
        {
            'name': 'The Dispatch',
            'feed_url': 'https://thedispatch.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - fact-based conservative journalism
        },
        {
            'name': 'Commentary Magazine',
            'feed_url': 'https://www.commentary.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 1.5  # Right - neoconservative intellectual magazine
        },
        {
            'name': 'The American Conservative',
            'feed_url': 'https://www.theamericanconservative.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 1.5  # Right - paleoconservative, non-interventionist
        },
        {
            'name': 'City Journal',
            'feed_url': 'https://www.city-journal.org/feed',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - Manhattan Institute, urban policy
        },
        {
            'name': 'The Federalist',
            'feed_url': 'https://thefederalist.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.70,
            'country': 'United States',
            'political_leaning': 1.5  # Right per MBFC - conservative opinion
        },
        {
            'name': 'Washington Examiner',
            'feed_url': 'https://www.washingtonexaminer.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 1.5  # Right per AllSides - conservative news
        },
        {
            'name': 'Daily Wire',
            'feed_url': 'https://www.dailywire.com/feeds/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.70,
            'country': 'United States',
            'political_leaning': 2.0  # Right per AllSides - conservative media
        },
        {
            'name': 'The Spectator US',
            'feed_url': 'https://spectator.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 1.5  # Right - conservative opinion magazine
        },
        {
            'name': 'RealClearPolitics',
            'feed_url': 'https://www.realclearpolitics.com/index.xml',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 0.5  # Lean Right per AllSides - aggregator with conservative lean
        },
        {
            'name': 'The Free Press',
            'feed_url': 'https://www.thefp.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0.5  # Lean Right - Bari Weiss, heterodox journalism
        },
        {
            'name': 'Hot Air',
            'feed_url': 'https://hotair.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.70,
            'country': 'United States',
            'political_leaning': 1.5  # Right per MBFC - conservative blog
        },
        {
            'name': 'Power Line',
            'feed_url': 'https://www.powerlineblog.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.70,
            'country': 'United States',
            'political_leaning': 1.5  # Right per MBFC - conservative blog
        },
        {
            'name': 'Tablet Magazine',
            'feed_url': 'https://www.tabletmag.com/feed',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 0.5  # Lean Right - Jewish affairs, heterodox
        },
        {
            'name': 'Law & Liberty',
            'feed_url': 'https://lawliberty.org/feed/',
            'source_type': 'rss',
            'reputation_score': 0.80,
            'country': 'United States',
            'political_leaning': 1.0  # Centre-Right - legal/constitutional conservatism
        },

        # ==========================================================================
        # SPORTS SOURCES
        # ==========================================================================
        {
            'name': 'BBC Sport',
            'feed_url': 'https://feeds.bbci.co.uk/sport/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United Kingdom',
            'political_leaning': 0
        },
        {
            'name': 'ESPN',
            'feed_url': 'https://www.espn.com/espn/rss/news',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'The Athletic',
            'feed_url': 'https://theathletic.com/rss-feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0
        },
        {
            'name': 'Sky Sports',
            'feed_url': 'https://www.skysports.com/rss/12040',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United Kingdom',
            'political_leaning': 0
        },
        
        # ==========================================================================
        # HEALTH & SCIENCE SOURCES
        # ==========================================================================
        {
            'name': 'STAT News',
            'feed_url': 'https://www.statnews.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -0.5  # Left-Center per MBFC
        },
        {
            'name': 'Nature News',
            'feed_url': 'https://www.nature.com/nature.rss',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United Kingdom',
            'political_leaning': 0
        },
        {
            'name': 'Science Magazine',
            'feed_url': 'https://www.science.org/rss/news_current.xml',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United States',
            'political_leaning': 0
        },
        {
            'name': 'The Lancet',
            'feed_url': 'https://www.thelancet.com/rssfeed/lancet_current.xml',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United Kingdom',
            'political_leaning': 0
        },
        
        # ==========================================================================
        # CRYPTO & DIGITAL ASSETS SOURCES
        # ==========================================================================
        {
            'name': 'CoinDesk',
            'feed_url': 'https://www.coindesk.com/arc/outboundfeeds/rss/',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': 0
        },
        {
            'name': 'The Block',
            'feed_url': 'https://www.theblock.co/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0
        },
        {
            'name': 'Decrypt',
            'feed_url': 'https://decrypt.co/feed',
            'source_type': 'rss',
            'reputation_score': 0.75,
            'country': 'United States',
            'political_leaning': 0
        },
        
        # ==========================================================================
        # WIRE SERVICES
        # ==========================================================================
        {
            'name': 'Reuters',
            'feed_url': 'https://www.reutersagency.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United Kingdom',
            'political_leaning': 0
        },
        {
            'name': 'Associated Press',
            'feed_url': 'https://rsshub.app/apnews/topics/apf-topnews',
            'source_type': 'rss',
            'reputation_score': 0.95,
            'country': 'United States',
            'political_leaning': 0
        },
        {
            'name': 'Wall Street Journal',
            'feed_url': 'https://feeds.content.dowjones.io/public/rss/RSSWorldNews',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': 0.5  # Centre-Right - business news
        },
        {
            'name': 'The New York Times',
            'feed_url': 'https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml',
            'source_type': 'rss',
            'reputation_score': 0.9,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left
        },
        {
            'name': 'Time',
            'feed_url': 'https://time.com/feed/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left per AllSides
        },
        
        # ==========================================================================
        # ADDITIONAL TECH SOURCES
        # ==========================================================================
        {
            'name': 'Wired',
            'feed_url': 'https://www.wired.com/feed/rss',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': -2.0  # Left per AllSides
        },
        {
            'name': 'The Verge',
            'feed_url': 'https://www.theverge.com/rss/index.xml',
            'source_type': 'rss',
            'reputation_score': 0.8,
            'country': 'United States',
            'political_leaning': -1.0  # Lean Left per AllSides
        },
        
        # ==========================================================================
        # CLIMATE & ENERGY SOURCES
        # ==========================================================================
        {
            'name': 'Clean Energy Wire',
            'feed_url': 'https://www.cleanenergywire.org/rss.xml',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'Germany',
            'political_leaning': 0
        },
        {
            'name': 'E&E News',
            'feed_url': 'https://www.eenews.net/rss/',
            'source_type': 'rss',
            'reputation_score': 0.85,
            'country': 'United States',
            'political_leaning': 0
        },
    ]
    
    try:
        added = 0
        updated = 0
        
        for source_data in default_sources:
            existing = NewsSource.query.filter_by(name=source_data['name']).first()
            
            if existing:
                # Update existing source with new field values
                fields_to_update = ['feed_url', 'source_type', 'reputation_score', 'country', 'political_leaning']
                source_updated = False
                
                for field in fields_to_update:
                    if field in source_data:
                        current_value = getattr(existing, field, None)
                        new_value = source_data[field]
                        
                        # Update if field is None or different
                        if current_value is None or current_value != new_value:
                            setattr(existing, field, new_value)
                            source_updated = True
                
                if source_updated:
                    updated += 1
                    logger.info(f"Updated source: {source_data['name']}")
            else:
                # Add new source
                source = NewsSource(**source_data)
                db.session.add(source)
                added += 1
                logger.info(f"Added new source: {source_data['name']}")
        
        db.session.commit()
        logger.info(f"Source seeding complete: {added} added, {updated} updated")
        
    except Exception as e:
        logger.error(f"Error seeding default sources: {e}")
        db.session.rollback()


def check_all_sources_health() -> dict:
    """
    Check the health of all configured news sources.
    
    Useful for debugging and verifying RSS feeds work before going live.
    
    Returns:
        dict: {
            'total': int,
            'healthy': int,
            'unhealthy': int,
            'sources': [{'name': str, 'status': str, 'message': str, 'entry_count': int}]
        }
    
    Usage in Flask shell:
        from app.trending.news_fetcher import check_all_sources_health
        results = check_all_sources_health()
        for s in results['sources']:
            if s['status'] != 'ok':
                print(f"FAILED: {s['name']} - {s['message']}")
    """
    fetcher = NewsFetcher()
    sources = NewsSource.query.filter_by(is_active=True).all()
    
    results = {
        'total': len(sources),
        'healthy': 0,
        'unhealthy': 0,
        'sources': []
    }
    
    for source in sources:
        health = fetcher.check_source_health(source)
        source_result = {
            'name': source.name,
            'feed_url': source.feed_url,
            'status': health['status'],
            'message': health['message'],
            'entry_count': health.get('entry_count', 0)
        }
        results['sources'].append(source_result)
        
        if health['status'] == 'ok':
            results['healthy'] += 1
        else:
            results['unhealthy'] += 1
    
    logger.info(f"Health check complete: {results['healthy']}/{results['total']} healthy")
    
    return results


def reset_disabled_sources():
    """
    Re-enable sources that were auto-disabled due to errors.
    
    Use after fixing feed URLs or when a source comes back online.
    
    Returns:
        int: Number of sources re-enabled
    """
    disabled = NewsSource.query.filter_by(is_active=False).all()
    count = 0
    
    for source in disabled:
        source.is_active = True
        source.fetch_error_count = 0
        count += 1
        logger.info(f"Re-enabled source: {source.name}")
    
    db.session.commit()
    return count
