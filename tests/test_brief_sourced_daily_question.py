"""
Tests for brief-sourced daily question selection (press-vs-public loop).

Guards the failure mode where a code path exists but never fires in production.
"""

from datetime import date, timedelta

import pytest

from app import db
from app.models import DailyBrief, BriefItem, TrendingTopic, DailyQuestion, Discussion
from app.daily.auto_selection import (
    BRIEF_SOURCE_TYPE,
    BriefQuestionWiringError,
    build_coverage_frame_snapshot,
    calculate_brief_item_contestability_score,
    get_eligible_brief_items,
    select_from_brief_items,
    select_next_question_source,
    schedule_question_from_brief,
    verify_brief_sourced_question_wiring,
    resolve_brief_primary_statement_id,
    wire_tomorrow_question_from_brief,
)


def _seed_brief_with_items(app, *, brief_date, items_spec):
    """items_spec: list of dicts with imbalance, underreported, seed_statements, primary_topic."""
    with app.app_context():
        db.create_all()
        brief = DailyBrief(
            date=brief_date,
            brief_type='daily',
            status='published',
            title=f'Brief {brief_date}',
        )
        db.session.add(brief)
        db.session.flush()

        created_items = []
        for idx, spec in enumerate(items_spec, start=1):
            topic = TrendingTopic(
                title=spec.get('title', f'Topic {idx}'),
                description='Test topic',
                primary_topic=spec.get('primary_topic', 'Politics'),
                civic_score=0.8,
                status='published',
                seed_statements=spec.get(
                    'seed_statements',
                    [{'content': 'Governments should increase funding for public services.', 'position': 'pro'}],
                ),
            )
            db.session.add(topic)
            db.session.flush()

            item = BriefItem(
                brief_id=brief.id,
                position=idx,
                section=spec.get('section', 'politics'),
                trending_topic_id=topic.id,
                headline=spec.get('headline', topic.title),
                coverage_distribution=spec.get(
                    'coverage_distribution',
                    {'left': 0.1, 'center': 0.2, 'right': 0.7},
                ),
                coverage_imbalance=spec.get('coverage_imbalance', 0.6),
                is_underreported=spec.get('is_underreported', False),
                source_count=spec.get('source_count', 5),
            )
            db.session.add(item)
            created_items.append((item, topic))

        db.session.commit()
        return brief.id, [(item.id, topic.id) for item, topic in created_items]


class TestBriefItemContestability:
    def test_balanced_broad_coverage_ranks_above_single_perspective(self):
        """
        Sign regression (July 2026): the original scorer rewarded *high*
        coverage_imbalance, i.e. stories only one bloc covered. Every zero-vote
        question in the 20-28 Jul corpus came from such an item.
        """
        contested = BriefItem(
            coverage_imbalance=0.25,
            coverage_distribution={'left': 0.25, 'center': 0.25, 'right': 0.5},
            source_count=7,
            is_underreported=False,
            section='lead',
        )
        ignored = BriefItem(
            coverage_imbalance=1.0,
            coverage_distribution={'left': 0.0, 'center': 1.0, 'right': 0.0},
            source_count=1,
            is_underreported=True,
            section='politics',
        )
        assert calculate_brief_item_contestability_score(contested) > (
            calculate_brief_item_contestability_score(ignored)
        )

    def test_underreported_flag_carries_no_selection_bonus(self):
        """Under-reported is a Brief virtue, not a question signal."""
        base = dict(
            coverage_imbalance=0.4,
            coverage_distribution={'left': 0.3, 'center': 0.4, 'right': 0.3},
            source_count=6,
            section='politics',
        )
        flagged = BriefItem(is_underreported=True, **base)
        plain = BriefItem(is_underreported=False, **base)
        assert calculate_brief_item_contestability_score(flagged) == (
            calculate_brief_item_contestability_score(plain)
        )

    def test_missing_coverage_metadata_does_not_raise(self):
        """Older items carry no distribution/perspectives; degrade, don't crash."""
        bare = BriefItem(section='politics')
        assert 0.0 <= calculate_brief_item_contestability_score(bare) <= 2.0

    def test_coverage_frame_snapshot_includes_dominant_frame(self, app):
        item = BriefItem(
            id=99,
            trending_topic_id=1,
            coverage_distribution={'left': 0.1, 'center': 0.1, 'right': 0.8},
            coverage_imbalance=0.7,
            is_underreported=True,
            source_count=4,
            section='lead',
        )
        snap = build_coverage_frame_snapshot(item, date(2026, 7, 14))
        assert snap['dominant_frame'] == 'right'
        assert snap['is_underreported'] is True
        assert snap['brief_item_id'] == 99


class TestBriefSourcedSelection:
    def test_select_from_brief_items_prefers_contested_over_ignored(self, app):
        """
        The story left, centre and right all covered — carrying a trade-off
        claim — must beat the single-outlet story carrying a civic pleasantry.
        """
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[
                {
                    'title': 'Single perspective story',
                    'coverage_imbalance': 0.95,
                    'coverage_distribution': {'left': 0.0, 'center': 1.0, 'right': 0.0},
                    'source_count': 1,
                    'is_underreported': True,
                    'seed_statements': [{
                        'content': 'Emergency response plans must be transparent and involve community input.',
                        'position': 'neutral',
                    }],
                },
                {
                    'title': 'Broadly contested story',
                    'coverage_imbalance': 0.2,
                    'coverage_distribution': {'left': 0.3, 'center': 0.4, 'right': 0.3},
                    'source_count': 9,
                    'section': 'lead',
                    'seed_statements': [{
                        'content': 'Investments in diplomatic solutions should be prioritized over military interventions.',
                        'position': 'pro',
                    }],
                },
            ],
        )

        with app.app_context():
            picks = {
                select_from_brief_items(brief_date, question_date)['source_trending_topic_id']
                for _ in range(12)
            }
            contested = TrendingTopic.query.filter_by(title='Broadly contested story').first()
            ignored = TrendingTopic.query.filter_by(title='Single perspective story').first()
            assert contested.id in picks
            assert ignored.id not in picks

    def test_select_from_brief_items_skips_non_votable_hedge_seeds(self, app):
        """E1 regression: hedge/question seeds must not become the daily stance."""
        brief_date = date(2026, 7, 16)
        question_date = date(2026, 7, 17)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[
                {
                    'title': 'Hedge only story',
                    'coverage_imbalance': 0.95,
                    'is_underreported': True,
                    'section': 'lead',
                    'seed_statements': [{
                        'content': (
                            'While updated data can provide valuable insights, we must '
                            'question what factors influence these statistics. Are they '
                            'reflecting actual humanitarian needs?'
                        ),
                        'position': 'neutral',
                    }],
                },
                {
                    'title': 'Clear claim story',
                    'coverage_imbalance': 0.4,
                    'seed_statements': [{
                        'content': (
                            'European governments should expand legal asylum capacity '
                            'rather than relying on deterrence alone.'
                        ),
                        'position': 'pro',
                    }],
                },
            ],
        )

        with app.app_context():
            source = select_from_brief_items(brief_date, question_date)
            assert source is not None
            assert 'should expand legal asylum' in source['question_text']
            assert 'valuable insights' not in source['question_text']

    def test_select_from_brief_items_returns_none_when_all_seeds_non_votable(self, app):
        brief_date = date(2026, 7, 16)
        question_date = date(2026, 7, 17)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[{
                'title': 'Only hedges',
                'coverage_imbalance': 0.9,
                'seed_statements': [{
                    'content': 'How can updated data on migration help us make better policies?',
                    'position': 'neutral',
                }],
            }],
        )
        with app.app_context():
            assert select_from_brief_items(brief_date, question_date) is None

    def test_clock_constraint_uses_yesterdays_brief_not_todays(self, app):
        yesterday = date(2026, 7, 14)
        today = date(2026, 7, 15)
        _seed_brief_with_items(
            app,
            brief_date=yesterday,
            items_spec=[{
                'title': 'Yesterday brief story',
                'coverage_imbalance': 0.75,
                'seed_statements': [{
                    'content': 'Governments should act on yesterday brief story findings.',
                    'position': 'pro',
                }],
            }],
        )
        _seed_brief_with_items(
            app,
            brief_date=today,
            items_spec=[{
                'title': 'Today brief story',
                'coverage_imbalance': 0.9,
                'seed_statements': [{
                    'content': 'Governments should act on today brief story findings.',
                    'position': 'pro',
                }],
            }],
        )

        # Fallback discussion so select_next_question_source never returns None
        with app.app_context():
            db.session.add(Discussion(
                title='Fallback discussion',
                slug='fallback-discussion-brief-clock',
                topic='Politics',
                geographic_scope='global',
                partner_env='live',
            ))
            db.session.commit()

            source = select_next_question_source(question_date=today)
            assert source['source_type'] == BRIEF_SOURCE_TYPE
            assert source['question_text'] == (
                'Governments should act on yesterday brief story findings.'
            )

    def test_schedule_question_from_brief_labels_provenance(self, app):
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        _brief_id, items = _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[{
                'coverage_imbalance': 0.7,
                'seed_statements': [{'content': 'Readers should judge this framed story.', 'position': 'pro'}],
            }],
        )
        expected_item_id, expected_topic_id = items[0]

        with app.app_context():
            question = schedule_question_from_brief(brief_date=brief_date, question_date=question_date)
            assert question is not None
            assert question.source_type == BRIEF_SOURCE_TYPE
            assert question.source_trending_topic_id == expected_topic_id
            assert question.source_brief_item_id == expected_item_id
            assert question.coverage_frame_json['brief_item_id'] == expected_item_id
            assert question.coverage_frame_json['brief_date'] == brief_date.isoformat()
            assert question.contestability_score is not None
            assert question.contestability_score > 0

            verify_brief_sourced_question_wiring(
                brief_date=brief_date,
                question_date=question_date,
            )

    def test_verify_guard_fails_when_eligible_but_unwired(self, app):
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[{'coverage_imbalance': 0.6}],
        )

        with app.app_context():
            with pytest.raises(BriefQuestionWiringError, match='Brief wiring dormant'):
                verify_brief_sourced_question_wiring(
                    brief_date=brief_date,
                    question_date=question_date,
                )

    def test_verify_guard_skips_when_no_eligible_items(self, app):
        with app.app_context():
            db.create_all()
            result = verify_brief_sourced_question_wiring(
                brief_date=date(2026, 7, 14),
                question_date=date(2026, 7, 15),
            )
            assert result['skipped'] is True

    def test_fallback_to_discussion_when_no_brief(self, app):
        with app.app_context():
            db.create_all()
            discussion = Discussion(
                title='Fallback civic topic',
                slug='fallback-civic-topic-brief',
                topic='Politics',
                geographic_scope='global',
                partner_env='live',
            )
            db.session.add(discussion)
            db.session.flush()
            from app.models import Statement
            db.session.add(Statement(
                discussion_id=discussion.id,
                content='Local councils should fund community resilience programmes.',
                is_seed=True,
            ))
            db.session.commit()

            source = select_next_question_source(question_date=date(2026, 7, 20))
            assert source is not None
            assert source['source_type'] == 'discussion'

    def test_get_eligible_brief_items_requires_seed_statements(self, app):
        brief_date = date(2026, 7, 14)
        with app.app_context():
            db.create_all()
            brief = DailyBrief(date=brief_date, brief_type='daily', status='published', title='Empty seeds')
            db.session.add(brief)
            db.session.flush()
            topic = TrendingTopic(title='No seeds', status='published', primary_topic='Politics')
            db.session.add(topic)
            db.session.flush()
            db.session.add(BriefItem(
                brief_id=brief.id,
                position=1,
                trending_topic_id=topic.id,
                coverage_imbalance=0.8,
            ))
            db.session.commit()
            assert get_eligible_brief_items(brief_date) == []

    def test_schedule_replaces_unpublished_existing_question(self, app):
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[{
                'coverage_imbalance': 0.65,
                'seed_statements': [{
                    'content': 'Brief wired replacement claim should be adopted.',
                    'position': 'pro',
                }],
            }],
        )

        with app.app_context():
            existing = DailyQuestion(
                question_date=question_date,
                question_number=1,
                question_text='Old discussion placeholder',
                source_type='discussion',
                status='scheduled',
            )
            db.session.add(existing)
            db.session.commit()

            updated = schedule_question_from_brief(brief_date=brief_date, question_date=question_date)
            assert updated.id == existing.id
            assert updated.source_type == BRIEF_SOURCE_TYPE
            assert updated.question_text == (
                'Brief wired replacement claim should be adopted.'
            )

    def test_wire_tomorrow_replaces_discussion_sourced_question(self, app):
        """Idempotent-skip scenario: existing brief + stale discussion question → brief."""
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        _seed_brief_with_items(
            app,
            brief_date=brief_date,
            items_spec=[{
                'coverage_imbalance': 0.72,
                'seed_statements': [{
                    'content': 'Brief side-door replacement claim should be adopted.',
                    'position': 'pro',
                }],
            }],
        )

        with app.app_context():
            existing = DailyQuestion(
                question_date=question_date,
                question_number=1,
                question_text='Stale discussion placeholder from auto-scheduler',
                source_type='discussion',
                status='scheduled',
            )
            db.session.add(existing)
            db.session.commit()

            result = wire_tomorrow_question_from_brief(brief_date=brief_date, source='primary_skip')
            assert result['ok'] is True
            assert result['question'].id == existing.id
            assert result['question'].source_type == BRIEF_SOURCE_TYPE
            assert result['question'].question_text == (
                'Brief side-door replacement claim should be adopted.'
            )

    def test_brief_source_sets_discussion_id_when_topic_has_discussion(self, app):
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        with app.app_context():
            db.create_all()
            discussion = Discussion(
                title='Linked civic discussion',
                slug='linked-civic-discussion-brief',
                topic='Politics',
                geographic_scope='global',
                partner_env='live',
            )
            db.session.add(discussion)
            db.session.flush()

            brief = DailyBrief(
                date=brief_date,
                brief_type='daily',
                status='published',
                title='Brief with linked topic',
            )
            db.session.add(brief)
            db.session.flush()

            topic = TrendingTopic(
                title='Linked topic',
                status='published',
                primary_topic='Politics',
                civic_score=0.8,
                discussion_id=discussion.id,
                seed_statements=[{
                    'content': 'Linked discussion claim for brief should be judged.',
                    'position': 'pro',
                }],
            )
            db.session.add(topic)
            db.session.flush()

            db.session.add(BriefItem(
                brief_id=brief.id,
                position=1,
                trending_topic_id=topic.id,
                coverage_imbalance=0.7,
                coverage_distribution={'left': 0.2, 'center': 0.2, 'right': 0.6},
            ))
            db.session.commit()

            question = schedule_question_from_brief(brief_date=brief_date, question_date=question_date)
            assert question.source_discussion_id == discussion.id
            assert question.source_trending_topic_id == topic.id

    def test_brief_source_sets_statement_id_when_seed_exists(self, app):
        brief_date = date(2026, 7, 14)
        question_date = date(2026, 7, 15)
        claim = 'Linked discussion claim for brief should be judged.'
        with app.app_context():
            db.create_all()
            discussion = Discussion(
                title='Linked civic discussion',
                slug='linked-civic-discussion-brief-statement',
                topic='Politics',
                geographic_scope='global',
                partner_env='live',
            )
            db.session.add(discussion)
            db.session.flush()

            from app.models import Statement

            seed = Statement(
                discussion_id=discussion.id,
                content=claim,
                is_seed=True,
            )
            db.session.add(seed)
            db.session.flush()

            brief = DailyBrief(
                date=brief_date,
                brief_type='daily',
                status='published',
                title='Brief with linked topic',
            )
            db.session.add(brief)
            db.session.flush()

            topic = TrendingTopic(
                title='Linked topic',
                status='published',
                primary_topic='Politics',
                civic_score=0.8,
                discussion_id=discussion.id,
                seed_statements=[{'content': claim, 'position': 'pro'}],
            )
            db.session.add(topic)
            db.session.flush()

            db.session.add(BriefItem(
                brief_id=brief.id,
                position=1,
                trending_topic_id=topic.id,
                coverage_imbalance=0.7,
                coverage_distribution={'left': 0.2, 'center': 0.2, 'right': 0.6},
            ))
            db.session.commit()

            question = schedule_question_from_brief(
                brief_date=brief_date, question_date=question_date
            )
            assert question.source_discussion_id == discussion.id
            assert question.source_statement_id == seed.id
            assert resolve_brief_primary_statement_id(claim, discussion.id) == seed.id
