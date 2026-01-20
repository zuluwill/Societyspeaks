"""
Unified Item Feed Service

Provides filtered access to ingested items across all features:
- Daily Brief: admin-approved sources only
- Trending/Discussions: news + current affairs
- User Briefings: user-selected sources

This service ensures editorial control while sharing a single ingestion pipeline.
"""

from datetime import datetime, timedelta
from typing import List, Optional
from sqlalchemy import and_, or_
from app import db
from app.models import InputSource, IngestedItem


class ItemFeedService:
    """
    Central service for accessing ingested content with editorial filtering.
    
    Channels:
    - 'daily_brief': Only admin-verified sources, no sport/entertainment
    - 'trending': News and current affairs sources
    - 'user_briefings': All sources the user has access to
    """
    
    CHANNEL_DAILY_BRIEF = 'daily_brief'
    CHANNEL_TRENDING = 'trending'
    CHANNEL_USER_BRIEFINGS = 'user_briefings'
    
    # Domains excluded from Daily Brief
    DAILY_BRIEF_EXCLUDED_DOMAINS = {'sport', 'entertainment', 'crypto', 'gaming'}
    
    @classmethod
    def get_items_for_channel(
        cls,
        channel: str,
        source_ids: Optional[List[int]] = None,
        days_back: int = 7,
        limit: int = 100,
        content_domains: Optional[List[str]] = None,
        exclude_domains: Optional[List[str]] = None,
    ) -> List[IngestedItem]:
        """
        Get items filtered by channel permissions.
        
        Args:
            channel: 'daily_brief', 'trending', or 'user_briefings'
            source_ids: Optional list of specific source IDs to include
            days_back: How many days of content to include
            limit: Maximum items to return
            content_domains: Optional list of domains to include
            exclude_domains: Optional list of domains to exclude
            
        Returns:
            List of IngestedItem instances
        """
        cutoff = datetime.utcnow() - timedelta(days=days_back)
        
        # Build source filter based on channel
        if source_ids:
            # Specific sources requested - verify they're allowed in this channel
            allowed_sources = cls._get_allowed_sources_for_channel(channel, source_ids)
            if not allowed_sources:
                return []
            source_filter = IngestedItem.source_id.in_(allowed_sources)
        else:
            # Get all enabled sources and filter in Python for JSONB compatibility
            all_sources = InputSource.query.filter(InputSource.enabled == True).all()
            
            # Filter sources by channel permission (Python-side for JSONB array check)
            filtered_sources = [s for s in all_sources if s.can_be_used_in(channel)]
            
            # Apply stricter requirements for daily_brief channel
            if channel == cls.CHANNEL_DAILY_BRIEF:
                # Must be verified and not in excluded domains
                filtered_sources = [
                    s for s in filtered_sources 
                    if getattr(s, 'is_verified', False) and 
                       s.content_domain not in cls.DAILY_BRIEF_EXCLUDED_DOMAINS
                ]
            
            if content_domains:
                filtered_sources = [s for s in filtered_sources if s.content_domain in content_domains]
            
            if exclude_domains:
                filtered_sources = [
                    s for s in filtered_sources 
                    if s.content_domain is None or s.content_domain not in exclude_domains
                ]
            
            allowed_source_ids = [s.id for s in filtered_sources]
            if not allowed_source_ids:
                return []
            source_filter = IngestedItem.source_id.in_(allowed_source_ids)
        
        # Query items
        items = IngestedItem.query.filter(
            source_filter,
            IngestedItem.fetched_at >= cutoff
        ).order_by(
            IngestedItem.published_at.desc().nullslast(),
            IngestedItem.fetched_at.desc()
        ).limit(limit).all()
        
        return items
    
    @classmethod
    def get_items_for_briefing(
        cls,
        briefing,
        days_back: int = 7,
        limit: int = 100
    ) -> List[IngestedItem]:
        """
        Get items for a specific briefing, respecting source associations.
        
        Args:
            briefing: Briefing instance
            days_back: How many days of content
            limit: Maximum items
            
        Returns:
            List of IngestedItem instances
        """
        # Get source IDs from briefing
        source_ids = [bs.source_id for bs in briefing.sources]
        if not source_ids:
            return []
        
        return cls.get_items_for_channel(
            channel=cls.CHANNEL_USER_BRIEFINGS,
            source_ids=source_ids,
            days_back=days_back,
            limit=limit
        )
    
    @classmethod
    def get_items_for_daily_brief(
        cls,
        days_back: int = 3,
        limit: int = 50
    ) -> List[IngestedItem]:
        """
        Get items suitable for the Daily Brief.
        Only returns content from admin-verified sources, excluding sport/entertainment.
        
        Args:
            days_back: How many days of content
            limit: Maximum items
            
        Returns:
            List of IngestedItem instances
        """
        return cls.get_items_for_channel(
            channel=cls.CHANNEL_DAILY_BRIEF,
            days_back=days_back,
            limit=limit
        )
    
    @classmethod
    def _get_allowed_sources_for_channel(
        cls,
        channel: str,
        source_ids: List[int]
    ) -> List[int]:
        """
        Filter source IDs to only those allowed in the given channel.
        Enforces both channel permissions AND domain restrictions.
        
        Args:
            channel: Channel name
            source_ids: List of source IDs to check
            
        Returns:
            List of allowed source IDs
        """
        sources = InputSource.query.filter(
            InputSource.id.in_(source_ids),
            InputSource.enabled == True
        ).all()
        
        allowed = []
        for s in sources:
            # Check channel permission
            if not s.can_be_used_in(channel):
                continue
            
            # Enforce stricter requirements for daily_brief channel
            if channel == cls.CHANNEL_DAILY_BRIEF:
                # Must be verified source
                if not getattr(s, 'is_verified', False):
                    continue
                # Exclude sport/entertainment/crypto/gaming domains
                if s.content_domain in cls.DAILY_BRIEF_EXCLUDED_DOMAINS:
                    continue
            
            allowed.append(s.id)
        
        return allowed
    
    @classmethod
    def get_source_health(cls, source_id: int) -> dict:
        """
        Get health status for a source.
        
        Args:
            source_id: Source ID
            
        Returns:
            Dict with health metrics
        """
        source = InputSource.query.get(source_id)
        if not source:
            return {'status': 'not_found'}
        
        recent_items = IngestedItem.query.filter(
            IngestedItem.source_id == source_id,
            IngestedItem.fetched_at >= datetime.utcnow() - timedelta(days=7)
        ).count()
        
        return {
            'status': 'healthy' if source.enabled and source.fetch_error_count == 0 else 'degraded',
            'enabled': source.enabled,
            'last_fetched': source.last_fetched_at.isoformat() if source.last_fetched_at else None,
            'error_count': source.fetch_error_count,
            'recent_items': recent_items,
            'origin_type': source.origin_type,
            'is_verified': source.is_verified,
            'allowed_channels': source.allowed_channels,
        }
    
    @classmethod
    def can_source_be_used_in(cls, source_id: int, channel: str) -> bool:
        """
        Check if a source can be used in a specific channel.
        
        Args:
            source_id: Source ID
            channel: Channel name
            
        Returns:
            True if allowed, False otherwise
        """
        source = InputSource.query.get(source_id)
        if not source:
            return False
        return source.can_be_used_in(channel)
