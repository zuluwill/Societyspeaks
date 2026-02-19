"""
Admin routes for Polymarket integration management.
"""

from flask import render_template, request, jsonify
from flask_login import login_required
from sqlalchemy import desc
from datetime import datetime, timedelta
from app.lib.time import utcnow_naive

from app import db
from app.models import PolymarketMarket, TopicMarketMatch, TrendingTopic
from app.admin import admin_bp
from app.admin.routes import admin_required
from app.polymarket.service import polymarket_service
from app.polymarket.matcher import market_matcher


@admin_bp.route('/polymarket/markets')
@login_required
@admin_required
def list_markets():
    """View all cached Polymarket markets with filtering."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    # Filters
    search = request.args.get('search', '').strip()
    category = request.args.get('category', '')
    quality_tier = request.args.get('quality_tier', '')
    active_only = request.args.get('active_only', 'true') == 'true'
    
    query = PolymarketMarket.query
    
    if active_only:
        query = query.filter(PolymarketMarket.is_active == True)
    
    if search:
        query = query.filter(
            db.or_(
                PolymarketMarket.question.ilike(f'%{search}%'),
                PolymarketMarket.description.ilike(f'%{search}%')
            )
        )
    
    if category:
        query = query.filter(PolymarketMarket.category == category)
    
    if quality_tier:
        if quality_tier == 'high':
            query = query.filter(PolymarketMarket.volume_24h >= PolymarketMarket.HIGH_QUALITY_VOLUME)
        elif quality_tier == 'medium':
            query = query.filter(
                PolymarketMarket.volume_24h >= PolymarketMarket.MIN_VOLUME_24H,
                PolymarketMarket.volume_24h < PolymarketMarket.HIGH_QUALITY_VOLUME
            )
        elif quality_tier == 'low':
            query = query.filter(PolymarketMarket.volume_24h < PolymarketMarket.MIN_VOLUME_24H)
    
    markets = query.order_by(desc(PolymarketMarket.volume_24h)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Get unique categories for filter
    categories = db.session.query(PolymarketMarket.category).distinct().all()
    categories = [c[0] for c in categories if c[0]]
    
    # Stats
    total_markets = PolymarketMarket.query.count()
    active_markets = PolymarketMarket.query.filter_by(is_active=True).count()
    high_quality = PolymarketMarket.query.filter(
        PolymarketMarket.volume_24h >= PolymarketMarket.HIGH_QUALITY_VOLUME,
        PolymarketMarket.is_active == True
    ).count()
    
    return render_template(
        'admin/polymarket/markets.html',
        markets=markets,
        categories=categories,
        search=search,
        category=category,
        quality_tier=quality_tier,
        active_only=active_only,
        stats={
            'total': total_markets,
            'active': active_markets,
            'high_quality': high_quality
        }
    )


@admin_bp.route('/polymarket/matches')
@login_required
@admin_required
def list_matches():
    """View topic-market matches with similarity scores."""
    page = request.args.get('page', 1, type=int)
    per_page = 50
    
    matches = TopicMarketMatch.query.join(TrendingTopic).join(PolymarketMarket).filter(
        PolymarketMarket.is_active == True
    ).order_by(desc(TopicMarketMatch.similarity_score)).paginate(
        page=page, per_page=per_page, error_out=False
    )
    
    # Stats
    total_matches = TopicMarketMatch.query.count()
    high_confidence = TopicMarketMatch.query.filter(
        TopicMarketMatch.similarity_score >= TopicMarketMatch.HIGH_CONFIDENCE_THRESHOLD
    ).count()
    
    return render_template(
        'admin/polymarket/matches.html',
        matches=matches,
        stats={
            'total': total_matches,
            'high_confidence': high_confidence
        }
    )


@admin_bp.route('/polymarket/health')
@login_required
@admin_required
def health_dashboard():
    """Sync status, error rates, market counts."""
    
    # Last sync time
    latest_market = PolymarketMarket.query.order_by(
        desc(PolymarketMarket.last_synced_at)
    ).first()
    
    last_sync = latest_market.last_synced_at if latest_market else None
    sync_stale = not last_sync or (utcnow_naive() - last_sync) > timedelta(hours=4)
    
    # Market counts
    active_markets = PolymarketMarket.query.filter_by(is_active=True).count()
    total_markets = PolymarketMarket.query.count()
    
    # Recent matches
    recent_matches = TopicMarketMatch.query.filter(
        TopicMarketMatch.created_at >= utcnow_naive() - timedelta(hours=24)
    ).count()
    
    # Markets needing embeddings
    markets_needing_embeddings = PolymarketMarket.query.filter(
        PolymarketMarket.question_embedding == None,
        PolymarketMarket.is_active == True
    ).count()
    
    # Quality breakdown
    high_quality = PolymarketMarket.query.filter(
        PolymarketMarket.volume_24h >= PolymarketMarket.HIGH_QUALITY_VOLUME,
        PolymarketMarket.is_active == True
    ).count()
    
    medium_quality = PolymarketMarket.query.filter(
        PolymarketMarket.volume_24h >= PolymarketMarket.MIN_VOLUME_24H,
        PolymarketMarket.volume_24h < PolymarketMarket.HIGH_QUALITY_VOLUME,
        PolymarketMarket.is_active == True
    ).count()
    
    status = 'healthy'
    if sync_stale:
        status = 'degraded'
    if active_markets == 0:
        status = 'unhealthy'
    
    return render_template(
        'admin/polymarket/health.html',
        status=status,
        last_sync=last_sync,
        sync_stale=sync_stale,
        active_markets=active_markets,
        total_markets=total_markets,
        recent_matches_24h=recent_matches,
        markets_needing_embeddings=markets_needing_embeddings,
        quality_breakdown={
            'high': high_quality,
            'medium': medium_quality,
            'low': active_markets - high_quality - medium_quality
        }
    )


@admin_bp.route('/polymarket/search')
@login_required
@admin_required
def search_markets():
    """Test search against Polymarket API."""
    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'markets': []})
    
    try:
        markets = polymarket_service.search_markets(query, limit=10)
        return jsonify({'markets': markets})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
