"""Society Play — game run persistence."""

from __future__ import annotations

import secrets
import uuid as uuid_lib
from datetime import datetime, timedelta, timezone

from app import db
from app.lib.time import utcnow_naive


class GameRun(db.Model):
    """A single player playthrough (daily slice, quick run, or campaign)."""

    __tablename__ = 'game_run'
    __table_args__ = (
        db.Index('idx_game_run_fingerprint_status', 'session_fingerprint', 'status'),
        db.Index('idx_game_run_user_status', 'user_id', 'status'),
        db.Index('idx_game_run_uuid', 'uuid', unique=True),
        # Partial index for participation counters (total + today). Selective and
        # small because it only covers completed runs, and ordered by started_at
        # so the day-range "today" count is a cheap index scan.
        db.Index(
            'idx_game_run_completed_started',
            'started_at',
            postgresql_where=db.text("status = 'completed'"),
            sqlite_where=db.text("status = 'completed'"),
        ),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid_lib.uuid4()))

    scenario_slug = db.Column(db.String(80), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default='daily')

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)

    society_name = db.Column(db.String(80), nullable=True)
    emblem_seed = db.Column(db.String(36), nullable=True)
    # Deterministic seed for opening-state variation (date-derived for dailies so
    # all players share the same opening; random for quick runs). NULL = baseline.
    variant_seed = db.Column(db.Integer, nullable=True)

    state_json = db.Column(db.JSON, nullable=False, default=dict)
    choice_log_json = db.Column(db.JSON, nullable=False, default=list)
    delayed_queue_json = db.Column(db.JSON, nullable=False, default=list)
    headline_log_json = db.Column(db.JSON, nullable=False, default=list)

    turn_index = db.Column(db.Integer, nullable=False, default=0)
    total_turns = db.Column(db.Integer, nullable=False, default=5)

    status = db.Column(db.String(20), nullable=False, default='in_progress')

    started_at = db.Column(db.DateTime, default=utcnow_naive)
    completed_at = db.Column(db.DateTime, nullable=True)
    last_active_at = db.Column(db.DateTime, default=utcnow_naive)

    user = db.relationship('User', backref='game_runs')
    outcome = db.relationship('GameRunOutcome', back_populates='run', uselist=False)

    @staticmethod
    def generate_uuid() -> str:
        return str(uuid_lib.uuid4())


class GameRunOutcome(db.Model):
    """Denormalised outcome for share pages and fast lookup."""

    __tablename__ = 'game_run_outcome'

    id = db.Column(db.Integer, primary_key=True)
    run_id = db.Column(db.Integer, db.ForeignKey('game_run.id'), nullable=False, unique=True)

    headline = db.Column(db.String(300), nullable=False)
    governance_label = db.Column(db.String(120), nullable=True)
    outcome_category = db.Column(db.String(40), nullable=True)

    axis_trust_autonomy = db.Column(db.Float, nullable=True)
    axis_prosperity_fairness = db.Column(db.Float, nullable=True)

    stat_finals_json = db.Column(db.JSON, nullable=False, default=dict)
    trait_chips_json = db.Column(db.JSON, nullable=False, default=list)
    contradiction_json = db.Column(db.JSON, nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    run = db.relationship('GameRun', back_populates='outcome')


class GameDailySchedule(db.Model):
    """UTC calendar assignment: one scenario slug per game day."""

    __tablename__ = 'game_daily_schedule'
    __table_args__ = (
        db.Index('idx_game_daily_schedule_date', 'schedule_date', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    schedule_date = db.Column(db.Date, nullable=False, unique=True)
    scenario_slug = db.Column(db.String(80), nullable=False)
    category_label = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)


class GameChallenge(db.Model):
    """Shareable friend challenge — creator headline revealed after friend completes."""

    __tablename__ = 'game_challenge'
    __table_args__ = (
        db.Index('idx_game_challenge_token', 'token', unique=True),
        db.Index('idx_game_challenge_creator_run', 'creator_run_id', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    token = db.Column(db.String(48), nullable=False, unique=True)
    creator_run_id = db.Column(
        db.Integer,
        db.ForeignKey('game_run.id', ondelete='CASCADE'),
        nullable=False,
        unique=True,
    )
    scenario_slug = db.Column(db.String(80), nullable=False)
    mode = db.Column(db.String(20), nullable=False)
    schedule_date = db.Column(db.Date, nullable=True)
    creator_display_name = db.Column(db.String(48), nullable=False, default='Someone')
    creator_headline = db.Column(db.String(300), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow_naive)

    creator_run = db.relationship('GameRun', foreign_keys=[creator_run_id])


class GameReminderSubscription(db.Model):
    """Opt-in daily nudge: 'today's scenario is live — keep your streak'.

    Supports authenticated users (``user_id``) and anonymous players (email +
    ``session_fingerprint``), mirroring the JourneyReminderSubscription pattern.
    Sending is gated by the daily play check (we never nag a player who already
    played today) and auto-pauses after ``MAX_CONSECUTIVE_MISSES`` unopened
    nudges for deliverability hygiene.
    """

    __tablename__ = 'game_reminder_subscription'
    __table_args__ = (
        db.Index('idx_game_reminder_next_send', 'next_send_at'),
        db.Index('idx_game_reminder_user', 'user_id'),
        db.Index('idx_game_reminder_fingerprint', 'session_fingerprint'),
        db.UniqueConstraint('email', name='uq_game_reminder_email'),
    )

    # Pause sending after this many consecutive nudges with no play, so dormant
    # inboxes don't keep receiving mail (protects sender reputation).
    MAX_CONSECUTIVE_MISSES = 5

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=True)
    email = db.Column(db.String(150), nullable=False)
    session_fingerprint = db.Column(db.String(64), nullable=True)

    timezone = db.Column(db.String(50), default='UTC', nullable=False)
    preferred_hour = db.Column(db.Integer, default=8, nullable=False)

    next_send_at = db.Column(db.DateTime, nullable=True)
    last_sent_at = db.Column(db.DateTime, nullable=True)
    reminder_count = db.Column(db.Integer, default=0, nullable=False)
    consecutive_misses = db.Column(db.Integer, default=0, nullable=False)

    unsubscribe_token = db.Column(db.String(255), nullable=True, unique=True)
    unsubscribed_at = db.Column(db.DateTime, nullable=True)
    unsubscribe_reason = db.Column(db.String(40), nullable=True)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    user = db.relationship('User', backref=db.backref('game_reminder_subscriptions', lazy='dynamic'))

    @property
    def is_active(self) -> bool:
        return self.unsubscribed_at is None

    def ensure_unsubscribe_token(self) -> str:
        """Stable token for indefinite unsubscribe links (CAN-SPAM / GDPR)."""
        if not self.unsubscribe_token:
            self.unsubscribe_token = secrets.token_urlsafe(32)
        return self.unsubscribe_token

    @staticmethod
    def find_by_unsubscribe_token(token):
        if not token:
            return None
        return GameReminderSubscription.query.filter_by(unsubscribe_token=token).first()

    def set_next_send_at(self, from_dt=None) -> datetime:
        """Schedule the next nudge at the player's local preferred hour.

        Computes the next occurrence of ``preferred_hour`` in the subscriber's
        timezone and stores it as naive UTC. If that slot is already past today,
        rolls to tomorrow — so we send at most one nudge per local day.
        """
        from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

        try:
            tz = ZoneInfo(self.timezone or 'UTC')
        except (ZoneInfoNotFoundError, ValueError, KeyError):
            tz = ZoneInfo('UTC')

        from_dt = from_dt or utcnow_naive()
        now_utc = from_dt.replace(tzinfo=timezone.utc)
        now_local = now_utc.astimezone(tz)

        hour = self.preferred_hour if self.preferred_hour is not None else 8
        hour = max(0, min(23, int(hour)))
        target_local = now_local.replace(hour=hour, minute=0, second=0, microsecond=0)
        if target_local <= now_local:
            target_local = target_local + timedelta(days=1)

        target_utc = target_local.astimezone(timezone.utc).replace(tzinfo=None)
        self.next_send_at = target_utc
        return target_utc
