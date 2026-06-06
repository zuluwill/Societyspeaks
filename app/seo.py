# app/seo.py
"""Sitemap generation for search engines and discovery crawlers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterator, Optional, Sequence
from xml.sax.saxutils import escape as xml_escape

from flask import current_app, has_request_context, request, url_for

from app.discussions.query_utils import crawlable_discussions_query
from app.models import (
    Briefing,
    DailyBrief,
    DailyQuestion,
    Discussion,
    NewsSource,
    Programme,
)

# Sitemaps.org: 50,000 URLs per file; stay below with headroom for growth.
_SITEMAP_URL_WARN_THRESHOLD = 45_000

# A discussion's statements are its crawlable content (unique whether or not
# anyone has voted yet). Native discussions below this many *visible* statements
# render thin pages that Google reports as "Crawled - currently not indexed", so
# they are held back. Overridable via SITEMAP_MIN_STATEMENTS (set 0 to advertise
# every crawlable discussion).
_DISCUSSION_MIN_STATEMENTS = 3


@dataclass(frozen=True)
class SitemapUrl:
    """One <url> entry in the sitemap."""

    loc: str
    lastmod: Optional[date] = None
    changefreq: Optional[str] = None
    priority: Optional[str] = None


def get_base_url() -> str:
    """Canonical site origin for sitemap <loc> values."""
    configured = (current_app.config.get('BASE_URL') or '').strip().rstrip('/')
    if configured:
        return configured
    if has_request_context():
        proto = request.headers.get('X-Forwarded-Proto') or request.scheme
        host = request.headers.get('Host') or request.host
        if host:
            return f'{proto}://{host}'
    return 'https://societyspeaks.io'


def _external(endpoint: str, **values) -> str:
    """Build an absolute URL using configured BASE_URL, not the request Host header."""
    if has_request_context():
        path = url_for(endpoint, _external=False, **values)
    else:
        with current_app.test_request_context('/'):
            path = url_for(endpoint, _external=False, **values)
    if not path.startswith('/'):
        path = f'/{path}'
    return f'{get_base_url().rstrip("/")}{path}'


def _as_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    return None


def _format_lastmod(value: Optional[date]) -> Optional[str]:
    if value is None:
        return None
    return value.isoformat()


def _render_url(entry: SitemapUrl) -> list[str]:
    lines = ['  <url>', f'    <loc>{xml_escape(entry.loc)}</loc>']
    lastmod = _format_lastmod(entry.lastmod)
    if lastmod:
        lines.append(f'    <lastmod>{lastmod}</lastmod>')
    if entry.changefreq:
        lines.append(f'    <changefreq>{entry.changefreq}</changefreq>')
    if entry.priority is not None:
        lines.append(f'    <priority>{entry.priority}</priority>')
    lines.append('  </url>')
    return lines


def _dedupe_entries(entries: Sequence[SitemapUrl]) -> list[SitemapUrl]:
    seen: set[str] = set()
    unique: list[SitemapUrl] = []
    for entry in entries:
        if entry.loc in seen:
            continue
        seen.add(entry.loc)
        unique.append(entry)
    return unique


def _static_entries(*, game_enabled: bool, self_serve_trial: bool) -> list[SitemapUrl]:
    """Marketing, product hubs, help, legal — fixed routes only."""
    entries: list[SitemapUrl] = [
        SitemapUrl(_external('main.index'), changefreq='daily', priority='1.0'),
        SitemapUrl(_external('main.about'), changefreq='monthly', priority='0.8'),
        SitemapUrl(_external('main.platform'), changefreq='weekly', priority='0.9'),
        SitemapUrl(_external('main.donate'), changefreq='monthly', priority='0.7'),
        SitemapUrl(_external('main.faq'), changefreq='monthly', priority='0.6'),
        SitemapUrl(_external('main.privacy_policy'), changefreq='monthly', priority='0.5'),
        SitemapUrl(_external('main.terms_and_conditions'), changefreq='monthly', priority='0.5'),
        SitemapUrl(_external('main.content_policy'), changefreq='monthly', priority='0.5'),
        SitemapUrl(_external('discussions.search_discussions'), changefreq='daily', priority='0.9'),
        SitemapUrl(_external('discussions.news_feed'), changefreq='hourly', priority='0.9'),
        SitemapUrl(_external('daily.today'), changefreq='daily', priority='0.9'),
        SitemapUrl(_external('brief.today'), changefreq='daily', priority='0.9'),
        SitemapUrl(_external('brief.archive'), changefreq='weekly', priority='0.8'),
        SitemapUrl(_external('brief.methodology'), changefreq='monthly', priority='0.6'),
        SitemapUrl(_external('brief.weekly_latest'), changefreq='weekly', priority='0.8'),
        SitemapUrl(_external('brief.underreported'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('news.dashboard'), changefreq='hourly', priority='0.9'),
        SitemapUrl(_external('programmes.list_programmes'), changefreq='weekly', priority='0.8'),
        SitemapUrl(_external('sources.index'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('briefing.landing'), changefreq='weekly', priority='0.8'),
        SitemapUrl(_external('partner.hub'), changefreq='monthly', priority='0.8'),
        SitemapUrl(_external('partner.embed_generator'), changefreq='monthly', priority='0.7'),
        SitemapUrl(_external('partner.api_docs'), changefreq='monthly', priority='0.7'),
        SitemapUrl(_external('partner.rules_of_record'), changefreq='monthly', priority='0.6'),
        SitemapUrl(_external('help.help'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.getting_started'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.big_questions_journey'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.daily_question'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.daily_brief'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.news_dashboard'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.civic_infrastructure'), changefreq='weekly', priority='0.8'),
        SitemapUrl(_external('help.personal_briefs'), changefreq='monthly', priority='0.6'),
        SitemapUrl(_external('help.programmes'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.creating_discussions'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.managing_discussions'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.seed_comments'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.polis_algorithms'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.native_system'), changefreq='weekly', priority='0.7'),
        SitemapUrl(_external('help.news_feed'), changefreq='weekly', priority='0.7'),
    ]
    if game_enabled:
        entries.extend([
            SitemapUrl(_external('game.index'), changefreq='daily', priority='0.9'),
            SitemapUrl(_external('game.daily'), changefreq='daily', priority='0.85'),
            SitemapUrl(_external('game.editorial_principles'), changefreq='monthly', priority='0.6'),
        ])
        entries.extend(_game_quick_run_entries())
    if game_enabled:
        entries.append(
            SitemapUrl(_external('help.tradeoffs'), changefreq='weekly', priority='0.7'),
        )
    if self_serve_trial:
        entries.append(
            SitemapUrl(_external('briefing.sample_brief'), changefreq='monthly', priority='0.7'),
        )
    return entries


def _game_quick_run_entries() -> list[SitemapUrl]:
    from app.game.services.quick_run_service import quick_run_pool

    entries: list[SitemapUrl] = []
    for item in quick_run_pool(exclude_today=False):
        slug = item.get('scenario_slug')
        if not slug:
            continue
        entries.append(
            SitemapUrl(
                _external('game.quick_run', scenario_slug=slug),
                changefreq='monthly',
                priority='0.65',
            )
        )
    return entries


def _visible_statement_counts(discussion_ids: Sequence[int]) -> dict[int, int]:
    """Published (visible) statement count per discussion, in a single query."""
    if not discussion_ids:
        return {}
    from sqlalchemy import func

    from app import db
    from app.lib.participation_metrics import visible_statement_vote_filters
    from app.models import Statement

    rows = (
        db.session.query(Statement.discussion_id, func.count(Statement.id))
        .filter(Statement.discussion_id.in_(list(discussion_ids)))
        .filter(*visible_statement_vote_filters(Statement))
        .group_by(Statement.discussion_id)
        .all()
    )
    return {int(discussion_id): int(count) for discussion_id, count in rows}


def _discussion_entries() -> Iterator[SitemapUrl]:
    """Crawlable discussions with enough readable content to be worth indexing.

    Substance is measured by *content*, not participation: a discussion's
    statements are unique, indexable text whether or not anyone has voted yet.

    * Native discussions are included once they carry at least
      ``SITEMAP_MIN_STATEMENTS`` visible statements; never-seeded stubs (which
      Google reports as "Crawled - currently not indexed") are held back.
    * Pol.is embed discussions keep their statements in the external widget, so
      there is nothing local to count — they are always included.
    * The consensus results page is omitted entirely: anonymous crawlers hit the
      participation gate and only ever see a near-identical thin page (now marked
      ``noindex, follow``), so advertising it would waste crawl budget and feed
      "Duplicate without user-selected canonical".
    """
    min_statements = current_app.config.get(
        'SITEMAP_MIN_STATEMENTS', _DISCUSSION_MIN_STATEMENTS
    )
    discussions = (
        crawlable_discussions_query()
        .filter(Discussion.slug.isnot(None), Discussion.slug != '')
        .order_by(Discussion.updated_at.desc())
        .all()
    )
    if not discussions:
        return
    native_ids = [d.id for d in discussions if d.has_native_statements]
    statement_counts = _visible_statement_counts(native_ids)
    for discussion in discussions:
        if (
            discussion.has_native_statements
            and statement_counts.get(discussion.id, 0) < min_statements
        ):
            continue
        lastmod = _as_date(discussion.updated_at) or _as_date(discussion.created_at)
        yield SitemapUrl(
            _external(
                'discussions.view_discussion',
                discussion_id=discussion.id,
                slug=discussion.slug,
            ),
            lastmod=lastmod,
            changefreq='daily',
            priority='0.7',
        )


def _programme_entries() -> Iterator[SitemapUrl]:
    programmes = (
        Programme.query.filter(
            Programme.status == 'active',
            Programme.visibility == 'public',
            Programme.slug.isnot(None),
            Programme.slug != '',
        )
        .order_by(Programme.updated_at.desc())
        .all()
    )
    from app.programmes.journey import is_guided_journey_programme

    for programme in programmes:
        lastmod = _as_date(programme.updated_at) or _as_date(programme.created_at)
        yield SitemapUrl(
            _external('programmes.view_programme', slug=programme.slug),
            lastmod=lastmod,
            changefreq='weekly',
            priority='0.75',
        )
        if is_guided_journey_programme(programme):
            yield SitemapUrl(
                _external('programmes.programme_journey_recap', slug=programme.slug),
                lastmod=lastmod,
                changefreq='weekly',
                priority='0.7',
            )


def _source_entries() -> Iterator[SitemapUrl]:
    sources = (
        NewsSource.query.filter(
            NewsSource.is_active.is_(True),
            NewsSource.slug.isnot(None),
            NewsSource.slug != '',
        )
        .order_by(NewsSource.name.asc())
        .all()
    )
    for source in sources:
        yield SitemapUrl(
            _external('sources.view_source', slug=source.slug),
            lastmod=_as_date(source.updated_at) or _as_date(source.created_at),
            changefreq='weekly',
            priority='0.65',
        )


def _daily_brief_entries() -> Iterator[SitemapUrl]:
    briefs = (
        DailyBrief.query.filter_by(status='published')
        .order_by(DailyBrief.date.desc())
        .all()
    )
    for brief in briefs:
        lastmod = _as_date(brief.published_at) or brief.date
        if brief.brief_type == 'weekly':
            yield SitemapUrl(
                _external('brief.weekly_by_date', date_str=brief.date.strftime('%Y-%m-%d')),
                lastmod=lastmod,
                changefreq='weekly',
                priority='0.65',
            )
        else:
            yield SitemapUrl(
                _external('brief.view_date', date_str=brief.date.strftime('%Y-%m-%d')),
                lastmod=lastmod,
                changefreq='monthly',
                priority='0.65',
            )


def _daily_question_entries() -> Iterator[SitemapUrl]:
    questions = (
        DailyQuestion.query.filter_by(status='published')
        .order_by(DailyQuestion.question_date.desc())
        .all()
    )
    for question in questions:
        yield SitemapUrl(
            _external('daily.by_date', date_str=question.question_date.strftime('%Y-%m-%d')),
            lastmod=_as_date(question.published_at) or question.question_date,
            changefreq='monthly',
            priority='0.65',
        )


def _public_briefing_entries() -> Iterator[SitemapUrl]:
    briefings = (
        Briefing.query.filter_by(visibility='public')
        .order_by(Briefing.updated_at.desc())
        .all()
    )
    for briefing in briefings:
        yield SitemapUrl(
            _external('briefing.public_briefing', briefing_id=briefing.id),
            lastmod=_as_date(briefing.updated_at) or _as_date(briefing.created_at),
            changefreq='weekly',
            priority='0.6',
        )


def _collect_dynamic_entries() -> list[SitemapUrl]:
    entries: list[SitemapUrl] = []
    collectors = (
        _discussion_entries,
        _programme_entries,
        _source_entries,
        _daily_brief_entries,
        _daily_question_entries,
        _public_briefing_entries,
    )
    for collector in collectors:
        try:
            entries.extend(collector())
        except Exception as exc:
            current_app.logger.error('Sitemap: %s failed: %s', collector.__name__, exc)
    return entries


def generate_sitemap() -> str:
    """Generate sitemap XML with canonical, crawlable URLs only."""
    game_enabled = bool(current_app.config.get('GAME_ENABLED', True))
    self_serve_trial = bool(current_app.config.get('SELF_SERVE_TRIAL_ENABLED'))

    entries = _dedupe_entries([
        *_static_entries(game_enabled=game_enabled, self_serve_trial=self_serve_trial),
        *_collect_dynamic_entries(),
    ])

    if len(entries) >= _SITEMAP_URL_WARN_THRESHOLD:
        current_app.logger.warning(
            'Sitemap has %s URLs (approaching the 50,000 URL limit); consider a sitemap index.',
            len(entries),
        )

    xml_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for entry in entries:
        xml_lines.extend(_render_url(entry))
    xml_lines.append('</urlset>')
    return '\n'.join(xml_lines)
