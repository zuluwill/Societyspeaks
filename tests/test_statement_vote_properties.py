"""
``Statement`` vote-count properties against NULL counters.

The ``vote_count_*`` columns carry a Python-side ``default=0``, which does
nothing for rows inserted before the column existed or by raw SQL. These
properties are rendered straight into pages (the embed does
``agreement_rate * 100``), so a NULL has to degrade, not raise.
"""
import pytest

from app.models import Discussion, Statement, User, generate_slug


@pytest.fixture
def statement(app, db):
    with app.app_context():
        user = User(username='nullcounts', email='nullcounts@example.com',
                    password='hashed-password')
        db.session.add(user)
        db.session.flush()
        discussion = Discussion(
            title='Null Counters',
            slug=generate_slug('Null Counters'),
            creator_id=user.id,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        stmt = Statement(
            discussion_id=discussion.id,
            user_id=user.id,
            content='A statement whose counters are deliberately NULL.',
        )
        db.session.add(stmt)
        db.session.flush()
        yield stmt


def test_total_votes_treats_null_counters_as_zero(statement):
    statement.vote_count_agree = None
    statement.vote_count_disagree = None
    statement.vote_count_unsure = None
    assert statement.total_votes == 0


def test_agreement_rate_handles_a_null_agree_counter(statement):
    """The denominator guard alone was not enough: a NULL numerator over a
    non-zero denominator raised TypeError mid-render."""
    statement.vote_count_agree = None
    statement.vote_count_disagree = 3
    statement.vote_count_unsure = None
    assert statement.agreement_rate == 0
    # The embed formats this directly.
    assert f"{statement.agreement_rate * 100:.0f}%" == '0%'


def test_agreement_rate_handles_a_null_disagree_counter(statement):
    statement.vote_count_agree = 4
    statement.vote_count_disagree = None
    statement.vote_count_unsure = None
    assert statement.agreement_rate == 1.0


def test_controversy_score_survives_null_counters(statement):
    statement.vote_count_agree = None
    statement.vote_count_disagree = None
    statement.vote_count_unsure = None
    assert statement.controversy_score == 0


def test_to_dict_is_json_serialisable_with_null_counters(statement):
    import json

    statement.vote_count_agree = None
    statement.vote_count_disagree = 2
    statement.vote_count_unsure = None
    payload = statement.to_dict()
    assert payload['total_votes'] == 2
    assert payload['agreement_rate'] == 0
    json.dumps(payload)
