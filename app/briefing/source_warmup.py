"""
Synchronous source warm-up before paid brief generation.

Ensures IngestedItem rows exist for all configured sources before selection
runs. Used by the first-brief trial path and every scheduled/manual generation.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Optional

from app import db
from app.models import Briefing, InputSource


logger = logging.getLogger(__name__)


@dataclass
class WarmupResult:
    sources_total: int
    sources_processed: int
    items_added: int
    timed_out: bool
    errors: int


def warm_up_briefing_sources(
    briefing: Briefing,
    *,
    budget_seconds: float = 60.0,
    days_back: int = 7,
) -> WarmupResult:
    """
    Ingest RSS/content for each briefing source until ``budget_seconds`` elapses.

    Processes sources in briefing priority order (highest first). Returns stats
    for logging/analytics; never raises — generation proceeds with whatever
    content is already in the pool.
    """
    from app.briefing.ingestion.source_ingester import SourceIngester

    links = sorted(
        briefing.sources,
        key=lambda bs: -(getattr(bs, 'priority', 1) or 1),
    )
    source_ids = [bs.source_id for bs in links if bs.source_id]
    if not source_ids:
        return WarmupResult(0, 0, 0, False, 0)

    sources = {
        s.id: s
        for s in InputSource.query.filter(InputSource.id.in_(source_ids)).all()
    }

    ingester = SourceIngester()
    deadline = time.monotonic() + max(budget_seconds, 0.0)
    processed = 0
    items_added = 0
    errors = 0
    timed_out = False

    for source_id in source_ids:
        if time.monotonic() >= deadline:
            timed_out = True
            break

        source = sources.get(source_id)
        if not source or not source.enabled:
            continue

        try:
            new_items = ingester.ingest_source(source, days_back=days_back)
            processed += 1
            items_added += len(new_items or [])
        except Exception as exc:
            errors += 1
            logger.error(
                "Warm-up ingest failed for source %s (%s): %s",
                source_id, source.name, exc, exc_info=True,
            )
            db.session.rollback()

    if processed:
        logger.info(
            "Briefing %s warm-up: %s/%s sources, %s new items%s",
            briefing.id,
            processed,
            len(source_ids),
            items_added,
            " (timed out)" if timed_out else "",
        )

    return WarmupResult(
        sources_total=len(source_ids),
        sources_processed=processed,
        items_added=items_added,
        timed_out=timed_out,
        errors=errors,
    )


def warm_up_briefing_by_id(
    briefing_id: int,
    *,
    budget_seconds: Optional[float] = None,
    days_back: int = 7,
) -> Optional[WarmupResult]:
    """Load briefing and warm up sources. Returns None if briefing missing."""
    from flask import current_app

    briefing = db.session.get(Briefing, briefing_id)
    if not briefing:
        return None

    if budget_seconds is None:
        budget_seconds = float(
            current_app.config.get('BRIEFING_SOURCE_WARMUP_SECONDS', 60)
        )

    return warm_up_briefing_sources(
        briefing,
        budget_seconds=budget_seconds,
        days_back=days_back,
    )
