"""Tests for paid briefing editorial pipeline improvements."""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.briefing.story_clustering import (
    StoryCluster,
    attach_cluster_metadata,
    cluster_scored_items,
    headline_similarity,
)
from app.briefing.template_config import apply_template_config_to_briefing
from app.models.briefing import Briefing, BriefTemplate


def test_headline_similarity_detects_near_duplicates():
    a = "Google launches new AI design app for consumers"
    b = "Google unveils AI design app with new features"
    assert headline_similarity(a, b) >= 0.35


def test_cluster_scored_items_merges_same_story():
    primary = MagicMock(id=1, title="Google launches AI agents for search", source_id=1, source_name="TechCrunch")
    related = MagicMock(id=2, title="Google AI agents launch changes search experience", source_id=2, source_name="The Verge")
    other = MagicMock(id=3, title="EU passes new digital markets regulation", source_id=3, source_name="Politico EU")

    clusters = cluster_scored_items([
        (primary, 5.0),
        (related, 4.0),
        (other, 3.0),
    ])

    assert len(clusters) == 2
    assert clusters[0].primary is primary
    assert related in clusters[0].related
    assert clusters[1].primary is other


def test_attach_cluster_metadata_sets_also_covered():
    primary = MagicMock(id=1, title="Story", source_id=1, source_name="TechCrunch")
    related = MagicMock(id=2, title="Story alt", source_id=2, source_name="Ars Technica", url="https://example.com/a")
    cluster = StoryCluster(primary=primary, related=[related], score=1.0)

    attach_cluster_metadata(cluster)
    assert primary._cluster_also_covered == [("Ars Technica", "https://example.com/a")]


def test_apply_template_config_copies_filters_and_topics():
    template = BriefTemplate(
        name="AI & Technology",
        slug="technology-ai-regulation",
        default_filters={
            'topics': ['Technology', 'AI'],
            'focus': ['regulation'],
            'sub_domains': ['cyber'],
        },
        focus_keywords=['AI', 'security'],
        exclude_keywords=['hype', 'game-changer'],
    )
    briefing = Briefing(name="My AI & Technology", owner_type='user', owner_id=1)

    apply_template_config_to_briefing(briefing, template)

    assert briefing.topic_preferences == {'Technology': 2, 'AI': 2}
    assert 'AI' in briefing.filters_json['include_keywords']
    assert 'regulation' in briefing.filters_json['include_keywords']
    assert 'cyber' in briefing.filters_json['include_keywords']
    assert 'hype' in briefing.filters_json['exclude_keywords']


def test_coverage_block_below_threshold_returns_none():
    """Fewer than 3 rated sources → no signal → template hides the block."""
    from app.lib.editorial import coverage_block_for_items

    items = [
        SimpleNamespace(source=SimpleNamespace(name='A', political_leaning=-0.8)),
        SimpleNamespace(source=SimpleNamespace(name='B', political_leaning=0.0)),
    ]
    assert coverage_block_for_items(items) is None


def test_coverage_block_buckets_by_leaning_and_dedupes_sources():
    from app.lib.editorial import compute_coverage_distribution

    items = [
        SimpleNamespace(source=SimpleNamespace(name='Guardian', political_leaning=-0.7)),
        SimpleNamespace(source=SimpleNamespace(name='Guardian', political_leaning=-0.7)),  # dupe
        SimpleNamespace(source=SimpleNamespace(name='Reuters', political_leaning=0.0)),
        SimpleNamespace(source=SimpleNamespace(name='Telegraph', political_leaning=0.7)),
        SimpleNamespace(source=SimpleNamespace(name='Local Blog', political_leaning=None)),
    ]
    block = compute_coverage_distribution(items)
    assert block.left_count == 1   # Guardian deduped
    assert block.center_count == 1
    assert block.right_count == 1
    assert block.unrated_count == 1
    assert block.has_signal is True


def test_coverage_block_blindspot_detection():
    """One side ≤15% with opposite ≥30% → blindspot flagged."""
    from app.lib.editorial import compute_coverage_distribution

    # 4 left, 1 right → left_pct=80, right_pct=20. Not a blindspot (≥15).
    items = [
        SimpleNamespace(source=SimpleNamespace(name=n, political_leaning=-0.8))
        for n in ('L1', 'L2', 'L3', 'L4')
    ] + [SimpleNamespace(source=SimpleNamespace(name='R1', political_leaning=0.8))]
    assert compute_coverage_distribution(items).blindspot is None

    # 7 left, 0 right → left_pct=100, right_pct=0. Right blindspot.
    items = [
        SimpleNamespace(source=SimpleNamespace(name=f'L{i}', political_leaning=-0.8))
        for i in range(7)
    ]
    assert compute_coverage_distribution(items).blindspot == 'right'


def test_quality_gate_holds_single_source_brief():
    """Auto-send is suppressed when one source dominates the brief."""
    from app.lib.editorial import assess_brief_quality

    items = [SimpleNamespace(source_id=1) for _ in range(5)]  # all one source
    verdict = assess_brief_quality(items)
    assert verdict.should_hold is True
    assert 'single source' in (verdict.hold_reason or '').lower()


def test_quality_gate_holds_when_one_source_dominates():
    """7 of 10 items from one source → held."""
    from app.lib.editorial import assess_brief_quality

    items = (
        [SimpleNamespace(source_id=1) for _ in range(8)] +
        [SimpleNamespace(source_id=2)] +
        [SimpleNamespace(source_id=3)]
    )
    verdict = assess_brief_quality(items)
    assert verdict.should_hold is True


def test_quality_gate_passes_diverse_brief():
    """4 items across 4 sources sails through."""
    from app.lib.editorial import assess_brief_quality

    items = [SimpleNamespace(source_id=i) for i in (1, 2, 3, 4)]
    verdict = assess_brief_quality(items)
    assert verdict.should_hold is False
    assert verdict.hold_reason is None
    assert verdict.distinct_sources == 4


def test_notify_draft_ready_sends_for_held_auto_send_brief(app, db):
    """Held auto_send briefs must alert the owner — previously skipped."""
    from app.models import (
        Briefing, BriefRun, User, PricingPlan,
    )
    from app.lib.time import utcnow_naive
    from app.briefing.notifications import notify_draft_ready

    user = User(username='owner', email='owner@example.test')
    user.set_password('x' * 12)
    db.session.add(user)
    db.session.flush()

    briefing = Briefing(
        name='Held Brief', owner_type='user', owner_id=user.id,
        status='active', mode='auto_send',
    )
    db.session.add(briefing)
    db.session.flush()

    run = BriefRun(
        briefing_id=briefing.id, scheduled_at=utcnow_naive(),
        status='awaiting_approval',
        failure_reason='All items from one source — held for review.',
    )
    db.session.add(run)
    db.session.commit()

    captured: list = []

    def _capture_send(**kwargs):
        captured.append(kwargs)
        return True

    with patch(
        'app.briefing.notifications._send_draft_notification_email',
        side_effect=_capture_send,
    ):
        result = notify_draft_ready(run.id)

    assert result['success'] is True
    assert 'owner@example.test' in result['sent_to']
    assert captured and captured[0]['hold_reason'] == (
        'All items from one source — held for review.'
    )


def test_notify_draft_ready_skipped_for_approved_run(app, db):
    """Already-approved runs don't trigger the approval queue notification."""
    from app.models import Briefing, BriefRun, User
    from app.lib.time import utcnow_naive
    from app.briefing.notifications import notify_draft_ready

    user = User(username='owner2', email='owner2@example.test')
    user.set_password('x' * 12)
    db.session.add(user)
    db.session.flush()
    briefing = Briefing(
        name='B', owner_type='user', owner_id=user.id,
        status='active', mode='auto_send',
    )
    db.session.add(briefing)
    db.session.flush()
    run = BriefRun(
        briefing_id=briefing.id, scheduled_at=utcnow_naive(),
        status='approved',
    )
    db.session.add(run)
    db.session.commit()

    result = notify_draft_ready(run.id)
    assert result.get('skipped', '').startswith('status:approved')


def test_quality_gate_holds_one_item_brief():
    """A single-item brief is not a brief."""
    from app.lib.editorial import assess_brief_quality

    items = [SimpleNamespace(source_id=1)]
    verdict = assess_brief_quality(items)
    assert verdict.should_hold is True


def test_quality_gate_resolves_brief_run_item_source(app, db):
    """BriefRunItem has no source_id column — gate follows ingested_item."""
    from app.lib.editorial import assess_brief_quality
    from app.models import InputSource, IngestedItem, BriefRun, BriefRunItem
    from app.lib.time import utcnow_naive

    sources = [
        InputSource(owner_type='system', name='A', type='rss',
                    config_json={'url': 'https://a.test'}, enabled=True),
        InputSource(owner_type='system', name='B', type='rss',
                    config_json={'url': 'https://b.test'}, enabled=True),
    ]
    for s in sources:
        db.session.add(s)
    db.session.flush()

    ingested = [
        IngestedItem(source_id=sources[0].id, title='One', content_hash='h1',
                     fetched_at=utcnow_naive()),
        IngestedItem(source_id=sources[1].id, title='Two', content_hash='h2',
                     fetched_at=utcnow_naive()),
    ]
    for row in ingested:
        db.session.add(row)
    db.session.flush()

    run = BriefRun(briefing_id=1, scheduled_at=utcnow_naive(), status='generated_draft')
    db.session.add(run)
    db.session.flush()

    items = [
        BriefRunItem(brief_run_id=run.id, position=1, ingested_item_id=ingested[0].id,
                     headline='[UPDATE] One'),
        BriefRunItem(brief_run_id=run.id, position=2, ingested_item_id=ingested[1].id,
                     headline='[UPDATE] Two'),
    ]
    for item in items:
        db.session.add(item)
    db.session.commit()

    # Relationship must be loadable for the resolver.
    loaded = BriefRunItem.query.filter_by(brief_run_id=run.id).all()
    verdict = assess_brief_quality(loaded)
    assert verdict.should_hold is False
    assert verdict.distinct_sources == 2


def test_underreported_picks_only_single_source_story():
    """Multi-source clusters aren't 'under the radar'."""
    from app.lib.editorial import find_underreported_story
    from app.lib.time import utcnow_naive

    selected = SimpleNamespace(
        id=1, title='Selected', source_name='X', url='', content_text='',
        published_at=utcnow_naive(), fetched_at=utcnow_naive(),
    )
    well_covered = SimpleNamespace(
        id=2, title='Well covered', source_name='Y', url='', content_text='',
        published_at=utcnow_naive(), fetched_at=utcnow_naive(),
    )
    obscure = SimpleNamespace(
        id=3, title='Obscure but valuable', source_name='Z', url='https://z.com',
        content_text='Some context paragraph.',
        published_at=utcnow_naive(), fetched_at=utcnow_naive(),
    )

    pick = find_underreported_story(
        candidates=[selected, well_covered, obscure],
        selected_ids=[selected.id],
        cluster_source_counts={1: 1, 2: 3, 3: 1},
    )
    assert pick is not None
    assert pick.title == 'Obscure but valuable'
    assert pick.source_name == 'Z'


def test_brief_run_item_persists_cluster_data_in_columns(app, db):
    """Generator stores cluster data on real columns — no marker hack."""
    from app.models import InputSource, Briefing, BriefingSource, IngestedItem, BriefRun, BriefRunItem
    from app.briefing.generator import BriefingGenerator
    from app.lib.time import utcnow_naive

    source = InputSource(
        owner_type='system', name='Ars', type='rss',
        config_json={'url': 'https://ars.test/feed'},
        enabled=True, status='ready',
    )
    db.session.add(source)
    db.session.flush()

    briefing = Briefing(name="Tech", owner_type='user', owner_id=1, status='active')
    db.session.add(briefing)
    db.session.flush()
    db.session.add(BriefingSource(briefing_id=briefing.id, source_id=source.id))

    ingested = IngestedItem(
        source_id=source.id,
        title="Google launches AI agents",
        content_text="Google has launched a new product.",
        content_hash='abc123',
        fetched_at=utcnow_naive(),
    )
    db.session.add(ingested)
    db.session.flush()

    # Generator transient: simulate the clusterer having attached siblings.
    ingested._cluster_also_covered = [('The Verge', 'https://verge.test/x')]

    run = BriefRun(briefing_id=briefing.id, scheduled_at=utcnow_naive(), status='generated_draft')
    db.session.add(run)
    db.session.flush()

    generator = BriefingGenerator()
    generator.llm_available = False  # exercise the deterministic fallback
    run_item = generator._generate_brief_item(run, ingested, 1, briefing)
    db.session.add(run_item)
    db.session.commit()

    persisted = db.session.get(BriefRunItem, run_item.id)
    assert persisted.cluster_also_covered == [{'name': 'The Verge', 'url': 'https://verge.test/x'}]
    # No marker leakage into content_markdown.
    assert not (persisted.content_markdown or '').startswith('[ALSO_COVERED:')
    assert not (persisted.content_markdown or '').startswith('[What This Means]')


def test_paid_brief_body_template_renders_all_blocks(app, db):
    """End-to-end: the Jinja partial renders intro, takeaways, coverage,
    underreported, sections, story cards, and source roster from data alone."""
    from flask import render_template
    from app.models import InputSource, Briefing, BriefingSource, BriefRun, BriefRunItem
    from app.briefing.generator import BriefingGenerator
    from app.lib.editorial import compute_coverage_distribution, UnderreportedPick
    from app.lib.time import utcnow_naive

    # Three rated sources so the coverage block has signal.
    sources = [
        InputSource(owner_type='system', name='Guardian', type='rss',
                    config_json={'url': 'https://g.test'}, enabled=True,
                    political_leaning=-0.7),
        InputSource(owner_type='system', name='Reuters', type='rss',
                    config_json={'url': 'https://r.test'}, enabled=True,
                    political_leaning=0.0),
        InputSource(owner_type='system', name='Telegraph', type='rss',
                    config_json={'url': 'https://t.test'}, enabled=True,
                    political_leaning=0.7),
    ]
    for s in sources:
        db.session.add(s)
    db.session.flush()

    briefing = Briefing(
        name="My Tech Brief", owner_type='user', owner_id=1, status='active',
        accent_color='#1e40af',
    )
    db.session.add(briefing)
    db.session.flush()
    for s in sources:
        db.session.add(BriefingSource(briefing_id=briefing.id, source_id=s.id))

    run = BriefRun(briefing_id=briefing.id, scheduled_at=utcnow_naive(), status='generated_draft')
    db.session.add(run)
    db.session.flush()

    # Two story items — one with cluster + context, one without.
    db.session.add(BriefRunItem(
        brief_run_id=run.id, position=1,
        headline='[TECHNOLOGY] Google launches AI agents',
        topic_category='TECHNOLOGY',
        source_name='Guardian',
        source_url='https://g.test/ai-agents',
        summary_bullets=['Bullet one', 'Bullet two'],
        content_markdown='Some analysis paragraph.',
        cluster_also_covered=[{'name': 'Reuters', 'url': 'https://r.test/ai'}],
        context_label='Market Impact',
        context_insight='This reshapes how knowledge workers interact with their tools.',
    ))
    db.session.add(BriefRunItem(
        brief_run_id=run.id, position=2,
        headline='[REGULATION] EU passes AI Act amendment',
        topic_category='REGULATION',
        source_name='Telegraph',
        source_url='https://t.test/eu-ai',
        summary_bullets=['Bullet'],
        content_markdown='',
    ))
    db.session.commit()
    db.session.refresh(run)

    # Attach a fake source on each item for coverage computation. Items have
    # .source via the ingested_item relationship in production; here we pass
    # the SimpleNamespace pseudo-articles directly to compute_coverage.
    coverage = compute_coverage_distribution([
        SimpleNamespace(source=sources[0]),
        SimpleNamespace(source=sources[1]),
        SimpleNamespace(source=sources[2]),
    ])
    underreported = UnderreportedPick(
        title='A small story your sources caught',
        source_name='Reuters',
        url='https://r.test/small',
        summary='Reuters reported on a niche finding nobody else picked up.',
        published_at=utcnow_naive(),
    )

    generator = BriefingGenerator()
    section_buckets = generator._build_section_buckets(run, briefing)
    html = render_template(
        'briefing/_paid_brief_body.html',
        brief_run=run,
        briefing=briefing,
        accent_color=briefing.accent_color,
        intro_text="Three threads today: AI agents, EU regulation, and quiet wins from your sources.",
        key_takeaways=["AI tooling is consolidating.", "Regulation is catching up."],
        coverage_block=coverage,
        underreported=underreported,
        section_buckets=section_buckets,
        source_roster=generator._build_source_roster(run, briefing),
        category_colors=BriefingGenerator.CATEGORY_COLORS,
        context_box_colors=BriefingGenerator.CONTEXT_BOX_COLORS,
        parse_item_headline=BriefingGenerator._parse_item_category_headline,
    )

    # Editorial intro
    assert "Three threads today" in html
    # Key Takeaways
    assert "Key Takeaways" in html
    assert "AI tooling is consolidating" in html
    # Coverage block (3 rated sources → has signal)
    assert "Coverage perspective" in html
    assert "left" in html and "centre" in html and "right" in html
    # Underreported
    assert "Under the radar" in html
    assert 'Only Reuters' in html or 'Only' in html and 'Reuters' in html
    # No template_id → single fallback bucket. The apostrophe in
    # "Today's Stories" is entity-escaped (&#39;) by the template's
    # escape_i18n filter; check both halves of the heading separately.
    assert "Today&#39;s Stories" in html or "Today's Stories" in html
    # Story cards
    assert "Google launches AI agents" in html
    assert "EU passes AI Act amendment" in html
    # Cluster also-covered line
    assert "Also covered by" in html
    assert "Reuters" in html
    # Context box
    assert "Market Impact" in html
    # Source roster footer
    assert "Sources today" in html
    assert "Guardian" in html and "Telegraph" in html


def test_apply_news_source_metadata_copies_leaning_and_verified(app, db):
    from app.models import InputSource, NewsSource
    from app.briefing.source_bridge import apply_news_source_metadata

    news = NewsSource(
        name='The Guardian',
        feed_url='https://guardian.test/rss',
        source_type='rss',
        political_leaning=-1.5,
        is_active=True,
    )
    db.session.add(news)
    db.session.flush()

    src = InputSource(
        owner_type='system',
        name='The Guardian',
        type='rss',
        config_json={'url': 'https://guardian.test/rss'},
        enabled=True,
        status='ready',
    )
    apply_news_source_metadata(src, news)
    assert src.political_leaning == -1.5
    assert src.is_verified is True
    assert src.content_domain == 'news'


def test_warm_up_briefing_sources_processes_enabled_sources(app, db):
    from app.models import InputSource, Briefing, BriefingSource
    from app.briefing.source_warmup import warm_up_briefing_sources

    source = InputSource(
        owner_type='system',
        name='Test Warmup Source',
        type='rss',
        config_json={'url': 'https://example.com/feed'},
        enabled=True,
        status='ready',
    )
    db.session.add(source)
    db.session.flush()

    briefing = Briefing(name="Test", owner_type='user', owner_id=1, status='active')
    db.session.add(briefing)
    db.session.flush()
    db.session.add(BriefingSource(briefing_id=briefing.id, source_id=source.id))
    db.session.commit()

    with patch('app.briefing.ingestion.source_ingester.SourceIngester') as mock_cls:
        mock_cls.return_value.ingest_source.return_value = []
        with app.app_context():
            result = warm_up_briefing_sources(briefing, budget_seconds=5.0)

    assert result.sources_processed == 1
    mock_cls.return_value.ingest_source.assert_called_once()
