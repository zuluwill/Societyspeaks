#!/usr/bin/env python3
"""
Backfill missing slugs for NewsSource records.

Run with: python -m scripts.backfill_source_slugs
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import create_app, db
from app.models import NewsSource, generate_slug


def backfill_slugs():
    """Generate slugs for all NewsSource records that don't have one."""
    app = create_app()
    
    with app.app_context():
        sources_without_slugs = NewsSource.query.filter(
            (NewsSource.slug == None) | (NewsSource.slug == '')
        ).all()
        
        if not sources_without_slugs:
            print("All sources already have slugs. Nothing to do.")
            return
        
        print(f"Found {len(sources_without_slugs)} sources without slugs")
        
        updated = 0
        skipped = 0
        
        for source in sources_without_slugs:
            base_slug = generate_slug(source.name)
            if not base_slug:
                print(f"  Skipping source {source.id}: Cannot generate slug from name '{source.name}'")
                skipped += 1
                continue
            
            slug = base_slug
            suffix = 1
            
            while NewsSource.query.filter(
                NewsSource.slug == slug,
                NewsSource.id != source.id
            ).first():
                slug = f"{base_slug}-{suffix}"
                suffix += 1
            
            source.slug = slug
            updated += 1
            print(f"  {source.id}: '{source.name}' -> '{slug}'")
        
        db.session.commit()
        print(f"\nDone! Updated {updated} sources, skipped {skipped}")


if __name__ == '__main__':
    backfill_slugs()
