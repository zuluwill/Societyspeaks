"""
Source Ingester

Generalized source ingestion system that extends NewsFetcher.
Supports RSS, URL lists, webpages, and uploads (via InputSource).
"""

import logging
import hashlib
import feedparser
import requests
from datetime import datetime, timedelta
from typing import List, Optional
from app import db
from app.models import InputSource, IngestedItem
from app.briefing.ingestion.webpage_scraper import scrape_webpage
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger(__name__)


class SourceIngester:
    """
    Ingests content from InputSource instances.
    Creates IngestedItem records for each piece of content.
    
    Supports:
    - RSS feeds
    - URL lists (webpage scraping)
    - Uploads (uses extracted_text from InputSource)
    """
    
    def __init__(self):
        self.timeout = 10  # Request timeout in seconds
    
    def ingest_source(self, source: InputSource, days_back: int = 7) -> List[IngestedItem]:
        """
        Ingest content from an InputSource.
        
        Args:
            source: InputSource instance to ingest from
            days_back: How many days back to fetch (for RSS/URLs)
        
        Returns:
            List of newly created IngestedItem instances
        """
        if not source.enabled:
            logger.info(f"Skipping disabled source: {source.name}")
            return []
        
        if source.type == 'rss':
            return self._ingest_rss(source, days_back)
        elif source.type == 'url_list':
            return self._ingest_url_list(source, days_back)
        elif source.type == 'webpage':
            return self._ingest_single_webpage(source)
        elif source.type == 'upload':
            return self._ingest_upload(source)
        else:
            logger.warning(f"Unknown source type: {source.type}")
            return []
    
    def _ingest_rss(self, source: InputSource, days_back: int) -> List[IngestedItem]:
        """Ingest from RSS feed"""
        try:
            feed_url = source.config_json.get('url') if source.config_json else None
            if not feed_url:
                logger.warning(f"RSS source {source.name} has no URL in config_json")
                return []
            
            # Parse RSS feed
            feed = feedparser.parse(feed_url)
            
            if feed.bozo:
                logger.warning(f"RSS feed parse error for {source.name}: {feed.bozo_exception}")
            
            cutoff_date = datetime.utcnow() - timedelta(days=days_back)
            new_items = []
            
            for entry in feed.entries:
                try:
                    # Parse published date
                    published_at = None
                    if hasattr(entry, 'published_parsed') and entry.published_parsed:
                        published_at = datetime(*entry.published_parsed[:6])
                    elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                        published_at = datetime(*entry.updated_parsed[:6])
                    
                    # Skip old entries
                    if published_at and published_at < cutoff_date:
                        continue
                    
                    # Get content
                    content = entry.get('summary', '') or entry.get('description', '')
                    if hasattr(entry, 'content'):
                        content = ' '.join([c.value for c in entry.content])
                    
                    # Create content hash for deduplication
                    content_hash = hashlib.sha256(
                        f"{entry.get('link', '')}{entry.get('title', '')}".encode()
                    ).hexdigest()
                    
                    # Check if already ingested
                    existing = IngestedItem.query.filter_by(
                        source_id=source.id,
                        content_hash=content_hash
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Create IngestedItem
                    item = IngestedItem(
                        source_id=source.id,
                        title=entry.get('title', 'Untitled')[:500],
                        url=entry.get('link'),
                        source_name=source.name,
                        published_at=published_at,
                        content_text=content[:10000] if content else None,  # Limit content length
                        content_hash=content_hash,
                        metadata_json={
                            'author': entry.get('author'),
                            'tags': [tag.term for tag in entry.get('tags', [])]
                        }
                    )
                    
                    db.session.add(item)
                    new_items.append(item)
                    
                except Exception as e:
                    logger.error(f"Error processing RSS entry for {source.name}: {e}")
                    continue
            
            # Update source metadata
            source.last_fetched_at = datetime.utcnow()
            source.fetch_error_count = 0
            db.session.commit()
            
            logger.info(f"Ingested {len(new_items)} new items from RSS source {source.name}")
            return new_items
            
        except Exception as e:
            logger.error(f"Error ingesting RSS source {source.name}: {e}", exc_info=True)
            source.fetch_error_count = (source.fetch_error_count or 0) + 1
            db.session.commit()
            return []
    
    def _ingest_url_list(self, source: InputSource, days_back: int) -> List[IngestedItem]:
        """Ingest from list of URLs (webpage scraping)"""
        try:
            urls = source.config_json.get('urls', []) if source.config_json else []
            if not urls:
                logger.warning(f"URL list source {source.name} has no URLs in config_json")
                return []
            
            new_items = []
            
            for url in urls:
                try:
                    # Scrape webpage
                    scraped = scrape_webpage(url, timeout=self.timeout)
                    if not scraped:
                        continue
                    
                    # Create content hash
                    content_hash = hashlib.sha256(
                        f"{url}{scraped['title']}".encode()
                    ).hexdigest()
                    
                    # Check if already ingested
                    existing = IngestedItem.query.filter_by(
                        source_id=source.id,
                        content_hash=content_hash
                    ).first()
                    
                    if existing:
                        continue
                    
                    # Create IngestedItem
                    item = IngestedItem(
                        source_id=source.id,
                        title=scraped['title'][:500],
                        url=url,
                        source_name=source.name,
                        published_at=scraped.get('published_at'),
                        content_text=scraped['content'][:10000] if scraped['content'] else None,
                        content_hash=content_hash,
                        metadata_json={}
                    )
                    
                    db.session.add(item)
                    new_items.append(item)
                    
                except Exception as e:
                    logger.error(f"Error scraping URL {url} for source {source.name}: {e}")
                    continue
            
            # Update source metadata
            source.last_fetched_at = datetime.utcnow()
            source.fetch_error_count = 0
            db.session.commit()
            
            logger.info(f"Ingested {len(new_items)} new items from URL list source {source.name}")
            return new_items
            
        except Exception as e:
            logger.error(f"Error ingesting URL list source {source.name}: {e}", exc_info=True)
            source.fetch_error_count = (source.fetch_error_count or 0) + 1
            db.session.commit()
            return []
    
    def _ingest_single_webpage(self, source: InputSource) -> List[IngestedItem]:
        """Ingest from single webpage"""
        try:
            url = source.config_json.get('url') if source.config_json else None
            if not url:
                logger.warning(f"Webpage source {source.name} has no URL in config_json")
                return []
            
            # Check if already ingested recently
            recent = IngestedItem.query.filter_by(
                source_id=source.id
            ).order_by(IngestedItem.fetched_at.desc()).first()
            
            if recent and recent.fetched_at > datetime.utcnow() - timedelta(hours=24):
                logger.info(f"Webpage {source.name} was recently fetched, skipping")
                return []
            
            # Scrape webpage
            scraped = scrape_webpage(url, timeout=self.timeout)
            if not scraped:
                return []
            
            # Create content hash
            content_hash = hashlib.sha256(
                f"{url}{scraped['title']}".encode()
            ).hexdigest()
            
            # Check if already ingested
            existing = IngestedItem.query.filter_by(
                source_id=source.id,
                content_hash=content_hash
            ).first()
            
            if existing:
                # Update fetched_at
                existing.fetched_at = datetime.utcnow()
                db.session.commit()
                return []
            
            # Create IngestedItem
            item = IngestedItem(
                source_id=source.id,
                title=scraped['title'][:500],
                url=url,
                source_name=source.name,
                published_at=scraped.get('published_at'),
                content_text=scraped['content'][:10000] if scraped['content'] else None,
                content_hash=content_hash,
                metadata_json={}
            )
            
            db.session.add(item)
            source.last_fetched_at = datetime.utcnow()
            source.fetch_error_count = 0
            db.session.commit()
            
            logger.info(f"Ingested webpage {source.name}")
            return [item]
            
        except Exception as e:
            logger.error(f"Error ingesting webpage source {source.name}: {e}", exc_info=True)
            source.fetch_error_count = (source.fetch_error_count or 0) + 1
            db.session.commit()
            return []
    
    def _ingest_upload(self, source: InputSource) -> List[IngestedItem]:
        """Ingest from uploaded file (uses extracted_text)"""
        try:
            # Wait for extraction to complete
            if source.status == 'extracting':
                logger.info(f"Upload source {source.name} still extracting, skipping")
                return []
            
            if source.status != 'ready' or not source.extracted_text:
                logger.warning(f"Upload source {source.name} not ready (status: {source.status})")
                return []
            
            # Check if already ingested
            existing = IngestedItem.query.filter_by(
                source_id=source.id
            ).first()
            
            if existing:
                # Update if text changed
                if existing.content_text != source.extracted_text:
                    existing.content_text = source.extracted_text[:10000]
                    existing.fetched_at = datetime.utcnow()
                    db.session.commit()
                return []
            
            # Create content hash
            content_hash = hashlib.sha256(
                f"{source.storage_key}{source.extracted_text}".encode()
            ).hexdigest()
            
            # Create IngestedItem
            item = IngestedItem(
                source_id=source.id,
                title=source.name,
                url=None,  # Uploads don't have URLs
                source_name=source.name,
                published_at=source.created_at,  # Use upload date
                content_text=source.extracted_text[:10000],
                content_hash=content_hash,
                metadata_json={'type': 'upload', 'storage_key': source.storage_key}
            )
            
            db.session.add(item)
            source.last_fetched_at = datetime.utcnow()
            db.session.commit()
            
            logger.info(f"Ingested upload source {source.name}")
            return [item]
            
        except Exception as e:
            logger.error(f"Error ingesting upload source {source.name}: {e}", exc_info=True)
            db.session.rollback()
            return []
