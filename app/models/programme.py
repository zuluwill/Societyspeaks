"""
Programme models.

Programme — a collaborative deliberation container grouping multiple
Discussions, with optional company-profile ownership, visibility +
status controls, and geographic scope metadata.
ProgrammeSteward — invite-token-based steward role grants.
ProgrammeAccessGrant — explicit per-user access entries (used for
private programmes).
ProgrammeExportJob — async export job with retry/timeout state and the
artifact storage reference.

Moved here from app/models.py as part of the models-split refactor.
No event listeners. Cross-domain relationships (User, CompanyProfile,
Discussion) use string references.
"""

from datetime import timedelta

from app import db
from app.lib.time import utcnow_naive
from app.models._base import generate_slug


class Programme(db.Model):
    __tablename__ = 'programme'
    __table_args__ = (
        db.Index('ix_programme_slug', 'slug', unique=True),
        db.Index('ix_programme_creator_id', 'creator_id'),
        db.Index('ix_programme_company_profile_id', 'company_profile_id'),
        db.Index('ix_programme_visibility_status', 'visibility', 'status'),
        db.Index('ix_programme_scope_country', 'geographic_scope', 'country'),
    )

    id = db.Column(db.Integer, primary_key=True)
    slug = db.Column(db.String(150), nullable=False, unique=True)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=True)
    creator_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    company_profile_id = db.Column(
        db.Integer,
        db.ForeignKey('company_profile.id', ondelete='RESTRICT'),
        nullable=True
    )
    geographic_scope = db.Column(db.String(20), nullable=False, default='global')
    country = db.Column(db.String(100), nullable=True)
    logo_url = db.Column(db.String(255), nullable=True)
    themes = db.Column(db.JSON, nullable=False, default=list)
    phases = db.Column(db.JSON, nullable=False, default=list)
    cohorts = db.Column(db.JSON, nullable=False, default=list)
    visibility = db.Column(db.String(20), nullable=False, default='public')
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    company_profile = db.relationship('CompanyProfile', backref=db.backref('programmes', lazy='select'))
    discussions = db.relationship('Discussion', backref='programme', lazy='select')
    stewards = db.relationship('ProgrammeSteward', backref='programme', lazy='select')
    access_grants = db.relationship(
        'ProgrammeAccessGrant',
        backref='programme',
        lazy='select',
        cascade='all, delete-orphan'
    )

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        if not self.slug and self.name:
            self.slug = generate_slug(self.name)

    def update_slug(self):
        if self.name:
            self.slug = generate_slug(self.name)


class ProgrammeSteward(db.Model):
    __tablename__ = 'programme_steward'
    __table_args__ = (
        db.Index('ix_programme_steward_programme_id', 'programme_id'),
        db.Index('ix_programme_steward_user_id', 'user_id'),
        db.Index('ix_programme_steward_invite_token', 'invite_token', unique=True),
        db.UniqueConstraint('programme_id', 'user_id', name='uq_programme_steward_programme_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    pending_email = db.Column(db.String(150), nullable=True)  # set when inviting unregistered users
    role = db.Column(db.String(20), nullable=False, default='steward')
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='pending')
    invite_token = db.Column(db.String(255), nullable=True)
    invited_at = db.Column(db.DateTime, nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    invited_by = db.relationship('User', foreign_keys=[invited_by_id])

    @staticmethod
    def generate_invite_token():
        import secrets
        return secrets.token_urlsafe(32)


class ProgrammeAccessGrant(db.Model):
    __tablename__ = 'programme_access_grant'
    __table_args__ = (
        db.Index('ix_programme_access_programme_id', 'programme_id'),
        db.Index('ix_programme_access_user_id', 'user_id'),
        db.Index('ix_programme_access_status', 'status'),
        db.UniqueConstraint('programme_id', 'user_id', name='uq_programme_access_programme_user'),
    )

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id', ondelete='CASCADE'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    invited_by_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    status = db.Column(db.String(20), nullable=False, default='active')
    created_at = db.Column(db.DateTime, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)

    user = db.relationship('User', foreign_keys=[user_id])
    invited_by = db.relationship('User', foreign_keys=[invited_by_id])


class ProgrammeExportJob(db.Model):
    """Asynchronous programme export job + audit trail."""
    __tablename__ = 'programme_export_job'
    __table_args__ = (
        db.Index('idx_export_job_status_queued_at', 'status', 'queued_at'),
        db.Index('idx_export_job_programme_created', 'programme_id', 'created_at'),
        db.Index('idx_export_job_requested_by', 'requested_by_user_id', 'created_at'),
        db.Index('idx_export_job_dedupe', 'dedupe_key'),
    )

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_STALE = 'stale'
    STATUS_DEAD_LETTER = 'dead_letter'
    ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

    id = db.Column(db.Integer, primary_key=True)
    programme_id = db.Column(db.Integer, db.ForeignKey('programme.id'), nullable=False)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    export_format = db.Column(db.String(10), nullable=False, default='csv')
    cohort_slug = db.Column(db.String(80), nullable=True)
    dedupe_key = db.Column(db.String(255), nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_QUEUED)
    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=900)
    error_message = db.Column(db.Text, nullable=True)

    storage_key = db.Column(db.String(500), nullable=True)
    artifact_filename = db.Column(db.String(255), nullable=True)
    content_type = db.Column(db.String(100), nullable=True)
    artifact_size_bytes = db.Column(db.Integer, nullable=True)

    queued_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    programme = db.relationship('Programme', backref='export_jobs')
    requested_by = db.relationship('User', backref='programme_export_jobs')

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_timed_out(self):
        if self.status != self.STATUS_RUNNING or not self.started_at:
            return False
        return (utcnow_naive() - self.started_at) > timedelta(seconds=max(0, self.timeout_seconds or 0))
