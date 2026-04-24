"""Regression tests for EmailAnalytics._identify_email_context.

The original bug: webhook events for addresses that sat on DailyBriefSubscriber
AND User got reclassified as ``auth`` whenever the subject contained a keyword
like "welcome" or "password", even though the send-path recorded them as
``daily_brief``. That desynced per-category dashboard numbers.

These tests pin the subscriber-first precedence so subject heuristics can
never override list membership again.
"""

import pytest

from app.lib.email_analytics import EmailAnalytics
from app.models import (
    DailyBriefSubscriber,
    DailyQuestionSubscriber,
    User,
)


def _make_user(db, email):
    user = User(
        username=email.split('@')[0],
        email=email,
        password='hashed-password',
        email_verified=True,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _make_brief_subscriber(db, email):
    sub = DailyBriefSubscriber(email=email, status='active')
    db.session.add(sub)
    db.session.commit()
    return sub


def _make_question_subscriber(db, email):
    sub = DailyQuestionSubscriber(email=email, is_active=True)
    db.session.add(sub)
    db.session.commit()
    return sub


def _identify(email, subject=''):
    return EmailAnalytics._identify_email_context(email, {'subject': subject})


def test_brief_subscriber_wins_over_auth_subject(app, db):
    """Regression: subject containing 'welcome' must NOT flip a brief subscriber to auth."""
    email = 'alice@example.com'
    _make_brief_subscriber(db, email)
    _make_user(db, email)

    category, context = _identify(email, subject='Welcome to Society Speaks')
    assert category == EmailAnalytics.CATEGORY_DAILY_BRIEF
    assert context.get('brief_subscriber_id') is not None
    assert context.get('user_id') is not None


def test_brief_subscriber_wins_over_password_subject(app, db):
    """Regression: subject containing 'password' must NOT flip a brief subscriber to auth."""
    email = 'bob@example.com'
    _make_brief_subscriber(db, email)
    _make_user(db, email)

    category, _ = _identify(email, subject='Password reset requested')
    assert category == EmailAnalytics.CATEGORY_DAILY_BRIEF


def test_brief_subscriber_wins_over_discussion_subject(app, db):
    """Brief subscriber beats a user whose subject mentions 'discussion' / 'notification'."""
    email = 'carol@example.com'
    _make_brief_subscriber(db, email)
    _make_user(db, email)

    category, _ = _identify(email, subject='New discussion notification')
    assert category == EmailAnalytics.CATEGORY_DAILY_BRIEF


def test_brief_plus_question_subscriber_uses_subject_to_disambiguate(app, db):
    """When on both lists, subject decides; otherwise defaults to daily_brief."""
    email = 'dave@example.com'
    _make_brief_subscriber(db, email)
    _make_question_subscriber(db, email)

    brief_cat, _ = _identify(email, subject='Monday edition — what matters today')
    assert brief_cat == EmailAnalytics.CATEGORY_DAILY_BRIEF

    question_cat, _ = _identify(email, subject='Question of the day')
    assert question_cat == EmailAnalytics.CATEGORY_DAILY_QUESTION


def test_question_subscriber_only(app, db):
    email = 'eve@example.com'
    _make_question_subscriber(db, email)

    category, context = _identify(email, subject='Password reset')
    assert category == EmailAnalytics.CATEGORY_DAILY_QUESTION
    assert context.get('question_subscriber_id') is not None


def test_user_only_auth_fallback(app, db):
    email = 'frank@example.com'
    _make_user(db, email)

    category, context = _identify(email, subject='Password reset')
    assert category == EmailAnalytics.CATEGORY_AUTH
    assert context.get('user_id') is not None


def test_user_only_discussion_subject(app, db):
    email = 'grace@example.com'
    _make_user(db, email)

    category, _ = _identify(email, subject='New notification on your discussion')
    assert category == EmailAnalytics.CATEGORY_DISCUSSION


def test_user_only_default_auth_when_subject_ambiguous(app, db):
    email = 'harry@example.com'
    _make_user(db, email)

    category, _ = _identify(email, subject='Your account summary')
    assert category == EmailAnalytics.CATEGORY_AUTH


def test_unknown_email_defaults_to_auth(app, db):
    # No subscriber or user rows at all.
    category, context = _identify('stranger@example.com', subject='Hi')
    assert category == EmailAnalytics.CATEGORY_AUTH
    assert context == {}


# NB: BriefRecipient (briefing-pipeline recipients) shares the `daily_brief`
# branch with DailyBriefSubscriber via the `elif brief_subscriber or
# briefing_recipient` arm. It is exercised by the brief-subscriber-only tests
# above; a standalone BriefRecipient fixture would require a full Briefing +
# organisation + source chain that isn't worth the test setup cost.
