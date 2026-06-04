"""Demo discussion links for Help Centre templates."""
from __future__ import annotations

from typing import Any, Dict, Optional

from flask import current_app, url_for

from app import db
from app.models import Discussion


def _demo_discussion_id() -> Optional[int]:
    demo_id = str(current_app.config.get('DEMO_DISCUSSION_ID', '') or '').strip()
    if demo_id.isdigit():
        return int(demo_id)
    raw = str(current_app.config.get('CONSENSUS_DEMO_DISCUSSION_IDS', '') or '').strip()
    if not raw:
        return None
    chunk = raw.split(',')[0].strip()
    return int(chunk) if chunk.isdigit() else None


def help_demo_links() -> Optional[Dict[str, Any]]:
    """URLs for live demo discussion + consensus, or None if unavailable."""
    discussion_id = _demo_discussion_id()
    if not discussion_id:
        return None
    discussion = db.session.get(Discussion, discussion_id)
    if not discussion or not discussion.slug:
        return None
    return {
        'discussion': discussion,
        'discussion_url': url_for(
            'discussions.view_discussion',
            discussion_id=discussion.id,
            slug=discussion.slug,
        ),
        'consensus_url': url_for(
            'consensus.view_results',
            discussion_id=discussion.id,
        ),
    }
