"""
Backfill missing podcast articles using enclosure URL as fallback.
Run with: python scripts/backfill_podcast_articles.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db

app = create_app()
with app.app_context():
    from app.models import NewsSource, NewsArticle
    from app.trending.news_fetcher import clean_summary
    import feedparser
    import requests
    from datetime import datetime

    podcast_sources = NewsSource.query.filter_by(source_category='podcast', is_active=True).all()
    print(f"Found {len(podcast_sources)} podcast sources")
    total_added = 0

    for source in podcast_sources:
        try:
            resp = requests.get(
                source.feed_url, timeout=15,
                headers={'User-Agent': 'SocietySpeaks/1.0 (+https://societyspeaks.io)'}
            )
            resp.raise_for_status()
            feed = feedparser.parse(resp.content)
        except Exception as e:
            print(f"  SKIP {source.name}: {e}")
            continue

        if not feed.entries:
            print(f"  EMPTY {source.name}")
            continue

        added = 0
        for entry in feed.entries[:50]:
            external_id = entry.get('id') or entry.get('link', '')
            if not external_id:
                continue

            existing = NewsArticle.query.filter_by(
                source_id=source.id,
                external_id=external_id[:500]
            ).first()
            if existing:
                continue

            url = entry.get('link', '')
            if not url or not url.startswith(('http://', 'https://')):
                enclosures = entry.get('enclosures', [])
                if enclosures:
                    url = enclosures[0].get('url', '')
            if not url or not url.startswith(('http://', 'https://')):
                continue

            title = entry.get('title', '')
            if not title:
                continue

            published_at = None
            if hasattr(entry, 'published_parsed') and entry.published_parsed:
                try:
                    published_at = datetime(*entry.published_parsed[:6])
                except Exception:
                    pass
            elif hasattr(entry, 'updated_parsed') and entry.updated_parsed:
                try:
                    published_at = datetime(*entry.updated_parsed[:6])
                except Exception:
                    pass

            raw_summary = entry.get('summary', '') or entry.get('description', '')
            cleaned_summary = clean_summary(raw_summary) if raw_summary else None

            db.session.add(NewsArticle(
                source_id=source.id,
                external_id=external_id[:500],
                title=title[:500],
                summary=cleaned_summary,
                url=url[:1000],
                published_at=published_at
            ))
            added += 1

        try:
            db.session.commit()
            if added:
                print(f"  +{added:2d}  {source.name}")
            total_added += added
        except Exception as e:
            db.session.rollback()
            print(f"  ERR {source.name}: {e}")

    print(f"\nTotal new articles added: {total_added}")
