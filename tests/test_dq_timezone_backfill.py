"""`flask backfill-dq-subscriber-timezones` — a production data mutation.

Pins two things:

1. NULL timezone already resolves to UTC everywhere that matters, so the
   backfill is behaviour-neutral. If that ever stops being true, the command's
   "changes no send behaviour" claim becomes a lie and these tests fail.
2. The command only touches active NULL-timezone rows, and only after explicit
   confirmation — it destroys the "imported, never asked" signal that identifies
   the cohort worth emailing about delivery time.
"""

from datetime import datetime, timedelta

import pytest
from click.testing import CliRunner

from app.models import DailyQuestionSubscriber


TUESDAY = 1
TUE_0900 = datetime(2026, 7, 28, 9, 0, 0)


def _subscriber(db, email, *, timezone=None, active=True, frequency='weekly'):
    s = DailyQuestionSubscriber(
        email=email,
        is_active=active,
        email_frequency=frequency,
        preferred_send_day=TUESDAY,
        preferred_send_hour=9,
        timezone=timezone,
    )
    s.generate_magic_token()
    db.session.add(s)
    db.session.commit()
    return s


def _invoke(app, args, input=None):
    runner = CliRunner()
    cmd = app.cli.get_command(None, 'backfill-dq-subscriber-timezones')
    assert cmd is not None, "command is not registered"
    with app.app_context():
        return runner.invoke(cmd, args, input=input, obj=None)


# --------------------------------------------------------------------------
# The premise: NULL already behaves as UTC
# --------------------------------------------------------------------------

def test_null_timezone_already_resolves_to_utc_for_sending(db):
    """If this fails, the backfill is no longer behaviour-neutral."""
    null_tz = _subscriber(db, 'null@example.com', timezone=None)
    explicit = _subscriber(db, 'utc@example.com', timezone='UTC')

    assert null_tz.should_receive_weekly_digest_now(TUE_0900) is True
    assert explicit.should_receive_weekly_digest_now(TUE_0900) is True
    assert (
        null_tz.hours_until_next_weekly_digest(TUE_0900)
        == explicit.hours_until_next_weekly_digest(TUE_0900)
    )


def test_backfill_does_not_change_send_eligibility(db, app):
    s = _subscriber(db, 'null@example.com', timezone=None)
    before = (
        s.should_receive_weekly_digest_now(TUE_0900),
        s.hours_until_next_weekly_digest(TUE_0900),
    )

    result = _invoke(app, ['--yes'])
    assert result.exit_code == 0

    db.session.refresh(s)
    after = (
        s.should_receive_weekly_digest_now(TUE_0900),
        s.hours_until_next_weekly_digest(TUE_0900),
    )
    assert before == after


# --------------------------------------------------------------------------
# Scope
# --------------------------------------------------------------------------

def test_dry_run_reports_without_writing(db, app):
    s = _subscriber(db, 'null@example.com', timezone=None)

    result = _invoke(app, ['--dry-run'])

    assert result.exit_code == 0
    assert 'Dry run' in result.output
    db.session.refresh(s)
    assert s.timezone is None, "dry run must not write"


def test_dry_run_counts_the_weekly_cohort(db, app):
    _subscriber(db, 'w1@example.com', timezone=None, frequency='weekly')
    _subscriber(db, 'w2@example.com', timezone=None, frequency='weekly')
    _subscriber(db, 'd1@example.com', timezone=None, frequency='daily')

    result = _invoke(app, ['--dry-run'])

    assert 'Found 3' in result.output
    assert '2 on weekly' in result.output


def test_confirmation_is_required_and_declining_writes_nothing(db, app):
    s = _subscriber(db, 'null@example.com', timezone=None)

    result = _invoke(app, [], input='n\n')

    assert 'Aborted' in result.output
    db.session.refresh(s)
    assert s.timezone is None


def test_accepting_the_prompt_writes_utc(db, app):
    s = _subscriber(db, 'null@example.com', timezone=None)

    result = _invoke(app, [], input='y\n')

    assert result.exit_code == 0
    db.session.refresh(s)
    assert s.timezone == 'UTC'


def test_existing_timezones_are_never_overwritten(db, app):
    kept = _subscriber(db, 'ny@example.com', timezone='America/New_York')

    _invoke(app, ['--yes'])

    db.session.refresh(kept)
    assert kept.timezone == 'America/New_York'


def test_inactive_subscribers_are_left_alone(db, app):
    inactive = _subscriber(db, 'gone@example.com', timezone=None, active=False)

    _invoke(app, ['--yes'])

    db.session.refresh(inactive)
    assert inactive.timezone is None


def test_reports_cleanly_when_there_is_nothing_to_do(db, app):
    _subscriber(db, 'ny@example.com', timezone='America/New_York')

    result = _invoke(app, ['--dry-run'])

    assert result.exit_code == 0
    assert 'No active daily-question subscribers with NULL timezone' in result.output


def test_warns_that_the_signal_is_destroyed_before_writing(db, app):
    """The operator must be told what is lost, not just what is set."""
    _subscriber(db, 'null@example.com', timezone=None)

    result = _invoke(app, [], input='n\n')

    assert 'never asked' in result.output
    assert 'Send times do not change' in result.output
