"""Weekly brief generation: sections, representative item, and development lines.

Three defects this suite pins down:

1. Every non-lead story was filed under ``section='politics'``, so unrelated
   stories rendered beneath a "Policy & Governance" heading and the per-section
   caps in ``app/brief/sections.py`` were bypassed entirely.
2. Deduping by topic kept the *first* item seen, i.e. the earliest appearance —
   so a story that ran Monday to Friday reached the weekend reader as Monday's
   write-up.
3. The intro reported the whole week's item count (~68) while the edition
   shipped 7, and was one of three hardcoded strings chosen by seeded random.
"""

from datetime import date, timedelta
from unittest.mock import patch

import pytest

from app.brief.sections import SECTIONS, DEPTH_FULL, DEPTH_STANDARD
from app.brief.weekly_generator import (
    WEEKLY_SECTION_CAP,
    WEEKLY_STORY_LIMIT,
    WeeklyBriefGenerator,
)
from app.models import DailyBrief, BriefItem, TrendingTopic


WEEK_END = date(2026, 7, 26)
WEEK_START = WEEK_END - timedelta(days=6)


def _topic(db, title, *, primary_topic='politics', civic=0.8):
    t = TrendingTopic(title=title, primary_topic=primary_topic, civic_score=civic)
    db.session.add(t)
    db.session.flush()
    return t


def _daily(db, d):
    b = DailyBrief(date=d, brief_type='daily', status='published', title=f"Daily {d}")
    db.session.add(b)
    db.session.flush()
    return b


def _item(db, brief, topic, *, headline, position=1, section='politics',
          bullets=None, source_count=6):
    it = BriefItem(
        brief_id=brief.id, position=position, section=section, depth=DEPTH_STANDARD,
        trending_topic_id=topic.id, headline=headline,
        summary_bullets=bullets or [f"{headline} detail"],
        source_count=source_count, coverage_imbalance=0.2,
    )
    db.session.add(it)
    db.session.flush()
    return it


@pytest.fixture
def gen():
    g = WeeklyBriefGenerator()
    g.llm_available = False  # deterministic: no network in tests
    return g


# --------------------------------------------------------------------------
# Sections
# --------------------------------------------------------------------------

def test_non_lead_stories_keep_their_own_section(db, gen):
    """The core bug: everything after the lead was filed under 'politics'."""
    d = _daily(db, WEEK_END)
    specs = [
        ('economy', 'Bank holds rates'),
        ('science', 'AI Act enforcement slips'),
        ('society', 'Trusts resist publishing data'),
    ]
    items = [
        _item(db, d, _topic(db, h, primary_topic=s), headline=h, section=s, position=i)
        for i, (s, h) in enumerate(specs, start=1)
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    lineup = gen._select_weekly_lineup(gen._rank_weekly_stories(items, history), history)

    sections = {section for _, section, _ in lineup}
    assert 'lead' in sections
    assert sections - {'lead'} <= set(s for s, _ in specs)
    assert sections != {'lead', 'politics'}, "non-lead stories collapsed into politics"


def test_daily_lead_story_is_refiled_by_topic_category(db, gen):
    """A daily lead carries section='lead' and no topical section of its own."""
    d = _daily(db, WEEK_END)
    lead_topic = _topic(db, 'Water fines', primary_topic='environment')
    other = _topic(db, 'Rates hold', primary_topic='economy')
    items = [
        _item(db, d, lead_topic, headline='Water firms fined', section='lead', position=1),
        _item(db, d, other, headline='Bank holds rates', section='economy', position=2),
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    # Force the non-lead story to rank first so the ex-lead is not the weekly lead.
    ranked = [items[1], items[0]]
    lineup = gen._select_weekly_lineup(ranked, history)

    refiled = {id(i): s for i, s, _ in lineup}[id(items[0])]
    assert refiled == 'science', "environment topic should map to Science, Tech & Environment"
    assert refiled != 'lead'


def test_section_cap_yields_slots_to_other_sections(db, gen):
    """A run of same-section stories must not crowd out a lower-ranked section.

    Ranked order here is economy×5 then science×1. Without the cap the science
    story never makes the top slots; with it, economy stops at the cap and
    science is promoted ahead of the displaced economy stories.
    """
    d = _daily(db, WEEK_END)
    econ = [
        _item(db, d, _topic(db, f'Econ {i}', primary_topic='economy'),
              headline=f'Econ story {i}', section='economy', position=i)
        for i in range(1, 6)
    ]
    sci = _item(db, d, _topic(db, 'Sci', primary_topic='science'),
                headline='Science story', section='science', position=6)
    db.session.commit()

    history = gen._build_topic_history([d])
    lineup = gen._select_weekly_lineup(econ + [sci], history)  # explicit rank order

    sections = [section for _, section, _ in lineup]
    assert sections[0] == 'lead'
    # Economy is capped during selection...
    assert sections[1:1 + WEEKLY_SECTION_CAP] == ['economy'] * WEEKLY_SECTION_CAP
    # ...so the science story is promoted ahead of the displaced economy ones.
    sci_pos = next(i for i, (item, _, _) in enumerate(lineup) if item.id == sci.id)
    assert sci_pos == 1 + WEEKLY_SECTION_CAP
    assert sections[sci_pos] == 'science'
    assert sections[sci_pos + 1:] == ['economy'] * (len(sections) - sci_pos - 1)


def test_cap_never_shrinks_the_edition(db, gen):
    """A single-theme week must still ship a full edition, not a stub."""
    d = _daily(db, WEEK_END)
    items = [
        _item(db, d, _topic(db, f'Pol {i}', primary_topic='politics'),
              headline=f'Politics story {i}', section='politics', position=i)
        for i in range(1, WEEKLY_STORY_LIMIT + 3)
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    lineup = gen._select_weekly_lineup(gen._rank_weekly_stories(items, history), history)

    assert len(lineup) == WEEKLY_STORY_LIMIT


def test_every_assigned_section_is_a_real_section(db, gen):
    d = _daily(db, WEEK_END)
    items = [
        _item(db, d, _topic(db, f'S {i}', primary_topic=cat), headline=f'Story {i}',
              section=None, position=i)
        for i, cat in enumerate(['politics', 'economy', 'health', 'climate', 'nonsense'], 1)
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    lineup = gen._select_weekly_lineup(gen._rank_weekly_stories(items, history), history)

    for _, section, _ in lineup:
        assert section in SECTIONS


def test_top_ranked_story_leads_at_full_depth(db, gen):
    d = _daily(db, WEEK_END)
    items = [
        _item(db, d, _topic(db, f'S {i}', primary_topic='politics'),
              headline=f'Story {i}', position=i)
        for i in range(1, 4)
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    lineup = gen._select_weekly_lineup(gen._rank_weekly_stories(items, history), history)

    assert lineup[0][1] == 'lead'
    assert lineup[0][2] == DEPTH_FULL
    assert all(depth == DEPTH_STANDARD for _, _, depth in lineup[1:])


# --------------------------------------------------------------------------
# Representative item = latest appearance
# --------------------------------------------------------------------------

def test_weekly_carries_the_latest_appearance_not_the_first(db, gen):
    topic = _topic(db, 'Running story')
    first, last = None, None
    briefs = []
    for offset in range(3):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        it = _item(db, d, topic, headline=f"Day {offset} headline")
        if offset == 0:
            first = it
        last = it
    db.session.commit()

    history = gen._build_topic_history(briefs)
    ranked = gen._rank_weekly_stories([first, last], history)

    assert ranked[0].id == last.id
    assert ranked[0].headline == "Day 2 headline"
    assert ranked[0].id != first.id


def test_topic_history_is_ordered_by_brief_date(db, gen):
    topic = _topic(db, 'Running story')
    briefs = []
    # Insert out of order — ordering must come from the date, not insertion.
    for offset in (2, 0, 1):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        _item(db, d, topic, headline=f"Day {offset}")
    db.session.commit()

    history = gen._build_topic_history(briefs)
    dates = [a['date'] for a in history[topic.id]]
    assert dates == sorted(dates)
    assert history[topic.id][-1]['headline'] == "Day 2"


def test_ranking_is_stable_across_regeneration(db, gen):
    d = _daily(db, WEEK_END)
    items = [
        _item(db, d, _topic(db, f'S {i}', primary_topic='politics', civic=0.7),
              headline=f'Story {i}', position=i, source_count=6)
        for i in range(1, 6)
    ]
    db.session.commit()

    history = gen._build_topic_history([d])
    first = [i.id for i in gen._rank_weekly_stories(items, history)]
    second = [i.id for i in gen._rank_weekly_stories(list(reversed(items)), history)]
    assert first == second


# --------------------------------------------------------------------------
# Development lines
# --------------------------------------------------------------------------

def test_no_development_line_for_a_single_appearance(db, gen):
    gen.llm_available = True
    d = _daily(db, WEEK_END)
    topic = _topic(db, 'One-day story')
    item = _item(db, d, topic, headline='Only ran once')
    db.session.commit()

    history = gen._build_topic_history([d])
    with patch.object(gen, '_call_llm') as llm:
        assert gen._generate_development_line(item, history[topic.id]) is None
    assert not llm.called, "a one-day story has no development to describe"


def test_development_line_generated_for_a_running_story(db, gen):
    gen.llm_available = True
    topic = _topic(db, 'Running story')
    briefs = []
    for offset in range(3):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        _item(db, d, topic, headline=f"Day {offset}", bullets=[f"detail {offset}"])
    db.session.commit()

    history = gen._build_topic_history(briefs)
    item = history[topic.id][-1]['item']

    with patch.object(gen, '_call_llm', return_value='  "It escalated."  ') as llm:
        line = gen._generate_development_line(item, history[topic.id])

    assert line == 'It escalated.'
    prompt = llm.call_args[0][0]
    # The prompt must carry the whole timeline in date order.
    assert 'Day 0' in prompt and 'Day 2' in prompt
    assert prompt.index('Day 0') < prompt.index('Day 2')
    assert 'Introduce no new facts' in prompt


def test_development_line_is_none_without_llm(db, gen):
    topic = _topic(db, 'Running story')
    briefs = []
    for offset in range(2):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        _item(db, d, topic, headline=f"Day {offset}")
    db.session.commit()

    history = gen._build_topic_history(briefs)
    item = history[topic.id][-1]['item']
    assert gen._generate_development_line(item, history[topic.id]) is None


def test_development_line_survives_llm_failure(db, gen):
    gen.llm_available = True
    topic = _topic(db, 'Running story')
    briefs = []
    for offset in range(2):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        _item(db, d, topic, headline=f"Day {offset}")
    db.session.commit()

    history = gen._build_topic_history(briefs)
    item = history[topic.id][-1]['item']

    with patch.object(gen, '_call_llm', side_effect=RuntimeError('api down')):
        assert gen._generate_development_line(item, history[topic.id]) is None


def test_daily_items_never_carry_a_development_line(db):
    """weekly_development must stay null outside weekly editions."""
    d = _daily(db, WEEK_END)
    item = _item(db, d, _topic(db, 'Story'), headline='A story')
    db.session.commit()
    assert item.weekly_development is None


# --------------------------------------------------------------------------
# Intro
# --------------------------------------------------------------------------

def test_intro_counts_selected_stories_not_the_whole_week(db, gen):
    """The old intro said "synthesises 68 stories" while shipping 7."""
    d = _daily(db, WEEK_END)
    selected = [
        _item(db, d, _topic(db, f'S {i}'), headline=f'Story {i}', position=i)
        for i in range(1, 4)
    ]
    db.session.commit()

    intro = gen._generate_weekly_intro([d], selected, gen._build_topic_history([d]))
    assert '3 stories' in intro
    assert '68' not in intro


def test_intro_mentions_developing_stories_when_present(db, gen):
    topic = _topic(db, 'Running story')
    briefs = []
    for offset in range(3):
        b = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(b)
        _item(db, b, topic, headline=f"Day {offset}")
    db.session.commit()

    history = gen._build_topic_history(briefs)
    selected = [history[topic.id][-1]['item']]
    intro = gen._generate_weekly_intro(briefs, selected, history)
    assert 'developed' in intro


def test_intro_is_deterministic(db, gen):
    """Same input, same intro — no seeded random choice between variants."""
    d = _daily(db, WEEK_END)
    selected = [_item(db, d, _topic(db, 'S'), headline='Story')]
    db.session.commit()
    history = gen._build_topic_history([d])

    a = gen._generate_weekly_intro([d], selected, history)
    b = gen._generate_weekly_intro([d], selected, history)
    assert a == b


def test_intro_falls_back_when_llm_fails(db, gen):
    gen.llm_available = True
    d = _daily(db, WEEK_END)
    selected = [_item(db, d, _topic(db, 'S'), headline='Story')]
    db.session.commit()
    history = gen._build_topic_history([d])

    with patch.object(gen, '_call_llm', side_effect=RuntimeError('api down')):
        intro = gen._generate_weekly_intro([d], selected, history)

    assert intro
    assert '1 story' in intro


def test_intro_falls_back_on_empty_llm_response(db, gen):
    gen.llm_available = True
    d = _daily(db, WEEK_END)
    selected = [_item(db, d, _topic(db, 'S'), headline='Story')]
    db.session.commit()
    history = gen._build_topic_history([d])

    with patch.object(gen, '_call_llm', return_value='   '):
        intro = gen._generate_weekly_intro([d], selected, history)

    assert '1 story' in intro


# --------------------------------------------------------------------------
# End-to-end generation
# --------------------------------------------------------------------------

def test_generate_weekly_brief_end_to_end(db):
    """The whole path: seven days in, one correctly-shaped edition out."""
    topics = {
        'water': _topic(db, 'Water fines', primary_topic='environment', civic=0.9),
        'rates': _topic(db, 'Interest rates', primary_topic='economy', civic=0.85),
        'nhs': _topic(db, 'NHS data', primary_topic='health', civic=0.8),
        'ai': _topic(db, 'AI adverts', primary_topic='technology', civic=0.75),
        'lets': _topic(db, 'Short-term lets', primary_topic='housing', civic=0.7),
    }
    briefs = []
    for offset in range(7):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        # 'water' runs all week; the rest appear once each, on different days.
        _item(db, d, topics['water'], headline=f"Water day {offset}", section='lead',
              position=1)
        key = list(topics)[1:][offset % 4]
        _item(db, d, topics[key], headline=f"{key} story", section=None, position=2)
    db.session.commit()

    gen = WeeklyBriefGenerator()
    gen.llm_available = False

    with patch('app.brief.weekly_generator.UpcomingEvent') as ev:
        ev.get_upcoming.return_value = []
        with patch('app.brief.generator.BriefGenerator') as bg:
            bg.return_value._generate_world_events.return_value = None
            brief = gen.generate_weekly_brief(WEEK_END, auto_publish=True)

    assert brief is not None
    assert brief.brief_type == 'weekly'
    assert brief.week_start_date == WEEK_START
    assert brief.week_end_date == WEEK_END

    items = brief.items.order_by(BriefItem.position).all()
    assert 0 < len(items) <= WEEKLY_STORY_LIMIT

    # One item per topic, all sections real, exactly one lead.
    topic_ids = [i.trending_topic_id for i in items]
    assert len(topic_ids) == len(set(topic_ids))
    assert all(i.section in SECTIONS for i in items)
    assert [i.section for i in items].count('lead') == 1
    assert items[0].section == 'lead'
    assert items[0].depth == DEPTH_FULL

    # The week-long story leads, carried at its *latest* appearance.
    assert items[0].trending_topic_id == topics['water'].id
    assert items[0].headline == "Water day 6"

    # Nothing is dumped into politics by default.
    assert [i.section for i in items[1:]].count('politics') < len(items) - 1

    # Intro reflects the edition, not the week's item pool.
    assert f"{len(items)} stor" in brief.intro_text


def test_generate_weekly_brief_force_regenerates_published_edition(db):
    """--force must rebuild a ready/published weekly edition, not return early."""
    topics = {'water': _topic(db, 'Water fines', primary_topic='environment', civic=0.9)}
    for offset in range(7):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        _item(db, d, topics['water'], headline=f"Water day {offset}", section='lead', position=1)
    db.session.commit()

    gen = WeeklyBriefGenerator()
    gen.llm_available = False

    with patch('app.brief.weekly_generator.UpcomingEvent') as ev:
        ev.get_upcoming.return_value = []
        with patch('app.brief.generator.BriefGenerator') as bg:
            bg.return_value._generate_world_events.return_value = None
            first = gen.generate_weekly_brief(WEEK_END, auto_publish=True)
            first.intro_text = 'ORIGINAL INTRO'
            db.session.commit()

            second = gen.generate_weekly_brief(WEEK_END, auto_publish=True)
            assert second.id == first.id
            assert second.intro_text == 'ORIGINAL INTRO'

            third = gen.generate_weekly_brief(WEEK_END, auto_publish=True, force=True)
            assert third.id == first.id
            assert third.intro_text != 'ORIGINAL INTRO'
            assert third.item_count > 0


# --------------------------------------------------------------------------
# --force must not take a live edition offline
#
# Both weekly web routes (app/brief/routes.py) filter status='published', and
# the auto-publish job only promotes briefs dated today. Demoting an older
# published edition to 'ready' during a --force refresh would black out
# /brief/weekly with nothing able to promote it back.
# --------------------------------------------------------------------------

def _seed_week(db, *, topic_count=3):
    briefs = []
    topics = [
        _topic(db, f'T{i}', primary_topic=cat)
        for i, cat in enumerate(['politics', 'economy', 'science'][:topic_count])
    ]
    for offset in range(3):
        d = _daily(db, WEEK_START + timedelta(days=offset))
        briefs.append(d)
        for i, t in enumerate(topics, start=1):
            _item(db, d, t, headline=f'{t.title} day {offset}', position=i)
    db.session.commit()
    return briefs


def _generate(week_end=WEEK_END, **kwargs):
    gen = WeeklyBriefGenerator()
    gen.llm_available = False
    with patch('app.brief.weekly_generator.UpcomingEvent') as ev:
        ev.get_upcoming.return_value = []
        with patch('app.brief.generator.BriefGenerator') as bg:
            bg.return_value._generate_world_events.return_value = None
            return gen.generate_weekly_brief(week_end, **kwargs)


def test_force_keeps_a_published_edition_published(db):
    from app.lib.time import utcnow_naive

    _seed_week(db)
    brief = _generate(auto_publish=True)
    published_at = utcnow_naive()
    brief.status = 'published'
    brief.published_at = published_at
    db.session.commit()
    brief_id = brief.id

    regenerated = _generate(auto_publish=True, force=True)

    assert regenerated.id == brief_id, "force must reuse the existing edition row"
    assert regenerated.status == 'published', (
        "force demoted a live edition to 'ready' — /brief/weekly filters on "
        "'published' and the auto-publish job only promotes today's briefs, so "
        "this edition would go dark permanently"
    )
    assert regenerated.published_at == published_at, "original publish time must be preserved"
    assert regenerated.items.count() > 0


def test_force_rebuilds_items_from_current_source_content(db):
    """Regeneration must re-read the dailies, not keep the previous snapshot.

    Asserted via content rather than row ids: SQLite reassigns the same
    autoincrement ids after a DELETE empties the table, so comparing ids
    proves nothing either way.
    """
    briefs = _seed_week(db)
    brief = _generate(auto_publish=True)
    original_headlines = {i.headline for i in brief.items.all()}
    assert original_headlines

    # Rewrite the source dailies, then force a refresh.
    for daily in briefs:
        for item in daily.items.all():
            item.headline = f"REWRITTEN {item.headline}"
    db.session.commit()

    regenerated = _generate(auto_publish=True, force=True)
    new_headlines = {i.headline for i in regenerated.items.all()}

    assert new_headlines
    assert all(h.startswith('REWRITTEN ') for h in new_headlines), (
        "weekly still carries the pre-refresh snapshot"
    )
    assert not (new_headlines & original_headlines)


def test_force_does_not_accumulate_duplicate_items(db):
    _seed_week(db)
    first = _generate(auto_publish=True)
    count_before = first.items.count()

    regenerated = _generate(auto_publish=True, force=True)

    assert regenerated.items.count() == count_before, "old items were not cleared"
    topic_ids = [i.trending_topic_id for i in regenerated.items.all()]
    assert len(topic_ids) == len(set(topic_ids)), "duplicate topics after regeneration"


def test_force_leaves_a_ready_edition_ready(db):
    _seed_week(db)
    brief = _generate(auto_publish=True)
    assert brief.status == 'ready'

    regenerated = _generate(auto_publish=True, force=True)
    assert regenerated.status == 'ready'


def test_without_force_an_existing_edition_is_returned_untouched(db):
    _seed_week(db)
    brief = _generate(auto_publish=True)
    original_item_ids = {i.id for i in brief.items.all()}

    again = _generate(auto_publish=True)

    assert again.id == brief.id
    assert {i.id for i in again.items.all()} == original_item_ids


def test_a_brand_new_edition_is_not_marked_published(db):
    """was_published must not leak across the new-brief branch."""
    _seed_week(db)
    brief = _generate(auto_publish=True)
    assert brief.status == 'ready'
    assert brief.published_at is None
