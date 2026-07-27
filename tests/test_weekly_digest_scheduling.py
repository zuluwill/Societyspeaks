"""Weekly question digest: eligibility, next-window reporting, and log clarity.

The hourly job fires 168 times a week; each subscriber matches exactly one of
those hours. It used to log "Weekly digest: sent to 0 subscribers, skipped 0" on
the other 167 runs, which reads as a broken pipeline — and it ran the question
selection every time to produce that nothing.

Two behaviours are pinned here:
- Nobody due → no question selection, and a log line that says *why* nobody was
  due and when the next window opens.
- Somebody due → the send proceeds and the summary distinguishes failures from
  the already-sent and outside-window cohorts.
"""

from datetime import timedelta

import pytest
import pytz

from app.lib.time import utcnow_naive
from app.models import DailyQuestionSubscriber


TUESDAY = 1  # Monday=0


def _subscriber(db, *, email='reader@example.com', day=TUESDAY, hour=9,
                timezone='UTC', last_sent=None, frequency='weekly'):
    s = DailyQuestionSubscriber(
        email=email,
        is_active=True,
        email_frequency=frequency,
        preferred_send_day=day,
        preferred_send_hour=hour,
        timezone=timezone,
        last_weekly_email_sent=last_sent,
    )
    s.generate_magic_token()
    db.session.add(s)
    db.session.commit()
    return s


def _utc(year, month, day, hour):
    from datetime import datetime
    return datetime(year, month, day, hour, 0, 0)


# 2026-07-28 is a Tuesday.
TUE_0900 = _utc(2026, 7, 28, 9)
TUE_1700 = _utc(2026, 7, 28, 17)
SAT_1700 = _utc(2026, 7, 25, 17)


# --------------------------------------------------------------------------
# hours_until_next_weekly_digest
# --------------------------------------------------------------------------

def test_zero_hours_when_the_window_is_open_now(db):
    s = _subscriber(db)
    assert s.should_receive_weekly_digest_now(TUE_0900) is True
    assert s.hours_until_next_weekly_digest(TUE_0900) == 0


def test_hours_until_window_later_the_same_day(db):
    s = _subscriber(db, hour=17)
    assert s.hours_until_next_weekly_digest(TUE_0900) == 8


def test_rolls_to_next_week_once_todays_window_has_passed(db):
    """Saturday's run must not report Tuesday's window as being in the past."""
    s = _subscriber(db, day=TUESDAY, hour=9)
    hours = s.hours_until_next_weekly_digest(TUE_1700)
    assert hours == 7 * 24 - 8       # next Tuesday 09:00
    assert hours > 0


def test_hours_from_a_weekend_run(db):
    """The Fri/Sat runs that prompted the false alarm."""
    s = _subscriber(db, day=TUESDAY, hour=9)
    hours = s.hours_until_next_weekly_digest(SAT_1700)
    assert hours == 3 * 24 - 8       # Sat 17:00 → Tue 09:00
    assert 0 < hours < 168


def test_next_window_is_timezone_aware(db):
    utc_sub = _subscriber(db, email='utc@example.com', timezone='UTC')
    ny_sub = _subscriber(db, email='ny@example.com', timezone='America/New_York')
    assert (
        utc_sub.hours_until_next_weekly_digest(TUE_0900)
        != ny_sub.hours_until_next_weekly_digest(TUE_0900)
    )


def test_null_timezone_is_treated_as_utc(db):
    """109 imported subscribers have timezone=NULL — this must not raise."""
    s = _subscriber(db, timezone=None)
    assert s.hours_until_next_weekly_digest(TUE_0900) == 0


def test_invalid_timezone_falls_back_to_utc(db):
    s = _subscriber(db, timezone='Mars/Olympus_Mons')
    assert s.hours_until_next_weekly_digest(TUE_0900) == 0


def test_none_for_non_weekly_subscribers(db):
    s = _subscriber(db, frequency='daily')
    assert s.hours_until_next_weekly_digest(TUE_0900) is None


def test_next_window_always_within_a_week(db):
    for day in range(7):
        for hour in (0, 9, 17, 23):
            s = _subscriber(
                db, email=f'r{day}-{hour}@example.com', day=day, hour=hour
            )
            hours = s.hours_until_next_weekly_digest(TUE_1700)
            assert 0 <= hours <= 168, f"day={day} hour={hour} → {hours}"


# --------------------------------------------------------------------------
# Eligibility split — the three cohorts the old log conflated
# --------------------------------------------------------------------------

def test_outside_window_is_not_due(db):
    s = _subscriber(db, day=TUESDAY, hour=9)
    assert s.should_receive_weekly_digest_now(SAT_1700) is False


def test_already_sent_this_week_is_not_due(db):
    s = _subscriber(db, last_sent=utcnow_naive() - timedelta(days=2))
    assert s.should_receive_weekly_digest_now(TUE_0900) is True
    assert s.has_received_weekly_digest_this_week() is True


def test_sent_more_than_six_days_ago_is_due_again(db):
    s = _subscriber(db, last_sent=utcnow_naive() - timedelta(days=7))
    assert s.has_received_weekly_digest_this_week() is False


def test_never_sent_is_due(db):
    s = _subscriber(db, last_sent=None)
    assert s.has_received_weekly_digest_this_week() is False


# --------------------------------------------------------------------------
# Scheduler structure — the hourly job's shape
#
# The job body is a closure inside init_scheduler() and cannot be imported, so
# these follow the source-inspection convention of test_brief_scheduler_wiring.
# --------------------------------------------------------------------------

from pathlib import Path

SCHEDULER_SRC = (
    Path(__file__).resolve().parents[1] / 'app' / 'scheduler.py'
).read_text(encoding='utf-8')


def _weekly_digest_job_source():
    start = SCHEDULER_SRC.index('def _run_weekly_digest_in_thread')
    end = SCHEDULER_SRC.index('def _run_monthly_digest_in_thread')
    return SCHEDULER_SRC[start:end]


def test_eligibility_is_computed_before_question_selection():
    """No question selection on the ~167 runs an hour where nobody is due."""
    src = _weekly_digest_job_source()
    eligibility = src.index('should_receive_weekly_digest_now')
    # The call site, not the import at the top of the function.
    selection = src.index('select_questions_for_weekly_digest(days_back=')
    assert eligibility < selection, (
        "questions are selected before checking whether anyone is due — "
        "that is 167 wasted selections a week"
    )


def test_quiet_run_returns_before_selecting_questions():
    src = _weekly_digest_job_source()
    guard = src.index('if not due:')
    # The call site, not the import at the top of the function.
    selection = src.index('select_questions_for_weekly_digest(days_back=')
    assert guard < selection


def test_quiet_run_log_reports_the_next_window():
    src = _weekly_digest_job_source()
    assert '0 due this hour' in src
    assert 'next window in' in src
    assert 'hours_until_next_weekly_digest' in src


def test_skip_reasons_are_counted_separately():
    """'skipped 0' conflated outside-window with already-sent."""
    src = _weekly_digest_job_source()
    assert 'wrong_window' in src
    assert 'already_sent' in src
    assert 'skipped_count' not in src, "old conflated counter still present"


def test_failures_are_counted_and_escalate_the_log_level():
    src = _weekly_digest_job_source()
    assert 'failed_count' in src
    assert 'logger.warning if failed_count else logger.info' in src
