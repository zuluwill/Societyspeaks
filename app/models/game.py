"""Society Play — game run persistence."""

from __future__ import annotations

import uuid as uuid_lib

from app import db
from app.lib.time import utcnow_naive


class GameRun(db.Model):
    """A single player playthrough (daily slice, quick run, or campaign)."""

    __tablename__ = 'game_run'
    __table_args__ = (
        db.Index('idx_game_run_fingerprint_status', 'session_fingerprint', 'status'),
        db.Index('idx_game_run_user_status', 'user_id', 'status'),
        db.Index('idx_game_run_uuid', 'uuid', unique=True),
    )

    id = db.Column(db.Integer, primary_key=True)
    uuid = db.Column(db.String(36), nullable=False, unique=True, default=lambda: str(uuid_lib.uuid4()))

    scenario_slug = db.Column(db.String(80), nullable=False)
    mode = db.Column(db.String(20), nullable=False, default='daily')

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    session_fingerprint = db.Column(db.String(64), nullable=True)

    society_name = db.Column(db.String(80), nullable=True)
    emblem_seed = db.Column(db.String(36), nullable=True)

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
