"""
Self-serve consultation models.

A consultation is a thin layer over a ``Discussion``: the host asks one
question, the audience votes on statements by link, and the host receives a
report. Statements and votes live in the existing discussion tables; these
models hold the lifecycle, the frozen report, what was paid, and the
background work.

Related models (Discussion, User) use string references.
"""
import secrets
from datetime import timedelta

from sqlalchemy.ext.mutable import MutableDict

from app import db
from app.lib.time import utcnow_naive


def _new_token() -> str:
    """128 bits, URL-safe: unguessable, and short enough for a QR code."""
    return secrets.token_urlsafe(16)


class Consultation(db.Model):
    """One question, one audience, one report."""
    __tablename__ = 'consultation'
    __table_args__ = (
        db.Index('idx_consultation_owner_created', 'owner_user_id', 'created_at'),
        db.Index('idx_consultation_status_closes', 'status', 'closes_at'),
    )

    STATUS_DRAFT = 'draft'      # question written, statements not yet approved
    STATUS_LIVE = 'live'        # collecting votes
    STATUS_CLOSED = 'closed'    # voting over; the report is built from here
    STATUSES = (STATUS_DRAFT, STATUS_LIVE, STATUS_CLOSED)

    COVERED_BY_PURCHASE = 'purchase'
    COVERED_BY_PLAN = 'plan'
    COVERED_BY_COMPLIMENTARY = 'complimentary'
    COVERED_BY_TRIAL = 'trial'

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(
        db.Integer, db.ForeignKey('discussion.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    owner_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False)

    status = db.Column(db.String(20), nullable=False, default=STATUS_DRAFT)

    question = db.Column(db.String(300), nullable=False)
    context = db.Column(db.Text, nullable=True)
    organisation_name = db.Column(db.String(200), nullable=False)
    audience_label = db.Column(db.String(200), nullable=True)
    # How many people the host invited, when they know: lets the report give a response rate.
    audience_size = db.Column(db.Integer, nullable=True)

    # The participant link is /c/<access_token>. Rotating it cuts off the old link.
    access_token = db.Column(db.String(64), nullable=False, unique=True, default=_new_token)

    allow_audience_statements = db.Column(db.Boolean, nullable=False, default=False)
    show_results_to_participants = db.Column(db.Boolean, nullable=False, default=True)

    closes_at = db.Column(db.DateTime, nullable=True)
    published_at = db.Column(db.DateTime, nullable=True)
    closed_at = db.Column(db.DateTime, nullable=True)
    # Each host notice is sent once (or, for moderation, at most hourly).
    first_response_notified_at = db.Column(db.DateTime, nullable=True)
    low_turnout_notified_at = db.Column(db.DateTime, nullable=True)
    moderation_notified_at = db.Column(db.DateTime, nullable=True)

    # What entitled this consultation to go live.
    covered_by = db.Column(db.String(20), nullable=True)
    # The 30-day pass this consultation was taken live on. Many consultations
    # can share one pass; deleting one must not refund the pass.
    covered_by_purchase_id = db.Column(
        db.Integer,
        db.ForeignKey(
            'consultation_purchase.id',
            ondelete='SET NULL',
            use_alter=True,
            name='fk_consultation_covered_by_purchase',
        ),
        nullable=True,
        index=True,
    )

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    discussion = db.relationship(
        'Discussion', backref=db.backref('consultation', uselist=False, passive_deletes=True),
    )
    owner = db.relationship('User', backref=db.backref('consultations', passive_deletes=True))

    @property
    def is_draft(self) -> bool:
        return self.status == self.STATUS_DRAFT

    @property
    def is_live(self) -> bool:
        return self.status == self.STATUS_LIVE

    @property
    def is_closed(self) -> bool:
        return self.status == self.STATUS_CLOSED

    def rotate_access_token(self) -> str:
        self.access_token = _new_token()
        return self.access_token


class ConsultationReport(db.Model):
    """The findings of a consultation, frozen when it was built.

    ``data`` is computed by code from the votes and never edited afterwards;
    ``data_hash`` proves it. ``narrative`` holds the headline and suggested
    next questions, written by AI or, when that fails validation, by template.
    """
    __tablename__ = 'consultation_report'
    __table_args__ = (
        db.Index('idx_consultation_report_consultation', 'consultation_id', 'created_at'),
    )

    KIND_INTERIM = 'interim'
    KIND_FINAL = 'final'

    NARRATIVE_AI = 'ai'
    NARRATIVE_TEMPLATE = 'template'

    id = db.Column(db.Integer, primary_key=True)
    consultation_id = db.Column(
        db.Integer, db.ForeignKey('consultation.id', ondelete='CASCADE'), nullable=False,
    )
    kind = db.Column(db.String(20), nullable=False, default=KIND_FINAL)

    data = db.Column(MutableDict.as_mutable(db.JSON), nullable=False)
    data_hash = db.Column(db.String(64), nullable=False)
    narrative = db.Column(MutableDict.as_mutable(db.JSON), nullable=False)
    narrative_source = db.Column(db.String(20), nullable=False, default=NARRATIVE_TEMPLATE)

    # Object-storage key of the rendered PDF, once built.
    pdf_storage_key = db.Column(db.String(500), nullable=True)

    # Set when the host chooses to share: the report is then readable at /r/<share_token>.
    share_token = db.Column(db.String(64), nullable=True, unique=True)
    shared_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    consultation = db.relationship(
        'Consultation',
        backref=db.backref(
            'reports', order_by='ConsultationReport.created_at.desc()',
            cascade='all, delete-orphan', passive_deletes=True,
        ),
    )

    @property
    def is_shared(self) -> bool:
        return bool(self.share_token)

    def share(self, token: str = None) -> str:
        """Open the report to anyone with the link. ``token`` reuses a link
        already given out for an earlier report of the same consultation."""
        if not self.share_token:
            self.share_token = token or _new_token()
            self.shared_at = utcnow_naive()
        return self.share_token

    def unshare(self) -> None:
        self.share_token = None
        self.shared_at = None


class ConsultationPurchase(db.Model):
    """A one-off payment for a 30-day pass.

    The pass covers every consultation the organisation takes live from
    ``valid_from`` until ``valid_until``. A second payment starts when the
    earlier pass ends, so two charges never cover the same days. ``consumed_at``
    is set on the first consultation and is what ends the right to a refund:
    deleting a consultation must not hand the money back, and the window itself
    stays open until ``valid_until``.

    Unique on the Stripe checkout session, so a replayed webhook cannot credit
    the same payment twice. ``consultation_id`` is the legacy one-purchase-one-
    consultation link; new passes leave it empty and point from the consultation.
    """
    __tablename__ = 'consultation_purchase'
    __table_args__ = (
        db.Index('idx_consultation_purchase_user_status', 'user_id', 'status'),
    )

    STATUS_PAID = 'paid'
    STATUS_REFUNDING = 'refunding'  # claimed for a refund Stripe has not yet confirmed
    STATUS_REFUNDED = 'refunded'
    STATUS_DISPUTED = 'disputed'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    stripe_checkout_session_id = db.Column(db.String(255), nullable=False, unique=True)
    stripe_payment_intent_id = db.Column(db.String(255), nullable=True, index=True)
    stripe_charge_id = db.Column(db.String(255), nullable=True, index=True)

    amount_pence = db.Column(db.Integer, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='gbp')
    status = db.Column(db.String(20), nullable=False, default=STATUS_PAID)

    # Set on the first consultation taken live on this pass. That locks the
    # refund. The pass keeps covering further consultations until ``valid_until``.
    consumed_at = db.Column(db.DateTime, nullable=True)
    # ``valid_from`` is empty on a pass bought before the window was recorded;
    # those are treated as already started. A pass bought while another is
    # still open has ``valid_from`` in the future and cannot be used yet.
    valid_from = db.Column(db.DateTime, nullable=True)
    valid_until = db.Column(db.DateTime, nullable=True)
    consultation_id = db.Column(
        db.Integer, db.ForeignKey('consultation.id', ondelete='SET NULL'), nullable=True, unique=True,
    )
    refunded_at = db.Column(db.DateTime, nullable=True)
    # Set when this pass has been taken off an annual plan. Until then, an open
    # pass can still be credited if the account upgrades during the window.
    credited_at = db.Column(db.DateTime, nullable=True)
    # Set once the host has been emailed that this window is about to end.
    ending_notified_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    user = db.relationship('User', backref=db.backref('consultation_purchases', passive_deletes=True))
    consultation = db.relationship(
        'Consultation',
        foreign_keys=[consultation_id],
        backref=db.backref('purchase', uselist=False),
    )

    @property
    def is_unused(self) -> bool:
        """Paid, never used to keep a consultation open, and not taken off an
        annual plan, so it can be refunded."""
        return self.status == self.STATUS_PAID and self.consumed_at is None and self.credited_at is None

    @property
    def has_started(self) -> bool:
        return self.valid_from is None or self.valid_from <= utcnow_naive()

    @property
    def is_scheduled(self) -> bool:
        """Paid, and the window has not started yet."""
        return (
            self.status == self.STATUS_PAID
            and self.valid_from is not None
            and self.valid_until is not None
            and self.valid_from > utcnow_naive()
        )

    @property
    def is_current(self) -> bool:
        """Paid and inside the window, whether or not it has been used."""
        return (
            self.status == self.STATUS_PAID
            and self.has_started
            and self.valid_until is not None
            and self.valid_until > utcnow_naive()
        )


class ConsultationPlan(db.Model):
    """The annual unlimited plan for one account, mirrored from Stripe."""
    __tablename__ = 'consultation_plan'

    # Stripe statuses that still entitle the account (past_due keeps access
    # while Stripe retries the card, as for the other products).
    ACCESS_STATUSES = ('active', 'trialing', 'past_due')

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    stripe_subscription_id = db.Column(db.String(255), nullable=True, unique=True)
    status = db.Column(db.String(30), nullable=False, default='inactive')
    current_period_end = db.Column(db.DateTime, nullable=True)
    cancel_at_period_end = db.Column(db.Boolean, nullable=False, default=False)
    ending_notified_at = db.Column(db.DateTime, nullable=True)

    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    user = db.relationship('User', backref=db.backref('consultation_plan', uselist=False, passive_deletes=True))

    @property
    def grants_access(self) -> bool:
        return self.status in self.ACCESS_STATUSES


class BackgroundJob(db.Model):
    """Persisted queue item for work that must not run inside a web request.

    Same lifecycle as ``ConsensusJob``: claimed with SKIP LOCKED, retried up to
    ``max_attempts``, then dead-lettered. ``kind`` selects the handler.
    """
    __tablename__ = 'background_job'
    __table_args__ = (
        db.Index('idx_background_job_claim', 'status', 'run_after', 'queued_at'),
        db.Index('idx_background_job_dedupe', 'dedupe_key'),
        db.Index('idx_background_job_consultation', 'consultation_id', 'kind', 'created_at'),
        db.Index('idx_background_job_user_kind', 'user_id', 'kind', 'created_at'),
        # At most one queued or running job per dedupe key.
        db.Index(
            'uq_background_job_active_dedupe', 'dedupe_key', unique=True,
            postgresql_where=db.text("status IN ('queued', 'running')"),
            sqlite_where=db.text("status IN ('queued', 'running')"),
        ),
    )

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_STALE = 'stale'
    STATUS_DEAD_LETTER = 'dead_letter'
    ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(50), nullable=False)
    payload = db.Column(db.JSON, nullable=False, default=dict)
    result = db.Column(db.JSON, nullable=True)
    consultation_id = db.Column(
        db.Integer, db.ForeignKey('consultation.id', ondelete='CASCADE'), nullable=True,
    )
    # Who the work is for. Outlives the consultation, so usage limits still
    # count work done for one that has since been deleted.
    user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)

    dedupe_key = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(20), nullable=False, default=STATUS_QUEUED)

    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=300)
    error_message = db.Column(db.Text, nullable=True)

    # A failed attempt is retried no earlier than this.
    run_after = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    queued_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    consultation = db.relationship(
        'Consultation', backref=db.backref('jobs', passive_deletes=True),
    )

    @property
    def is_active(self) -> bool:
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_timed_out(self) -> bool:
        if self.status != self.STATUS_RUNNING or not self.started_at:
            return False
        return (utcnow_naive() - self.started_at) > timedelta(seconds=max(0, self.timeout_seconds or 0))


class LLMUsage(db.Model):
    """One platform LLM call: who it was for and what it consumed.

    The record the cost of a consultation is measured from.
    """
    __tablename__ = 'llm_usage'
    __table_args__ = (
        db.Index('idx_llm_usage_consultation', 'consultation_id', 'created_at'),
        db.Index('idx_llm_usage_purpose_created', 'purpose', 'created_at'),
    )

    id = db.Column(db.Integer, primary_key=True)
    purpose = db.Column(db.String(50), nullable=False)
    provider = db.Column(db.String(20), nullable=False)
    model = db.Column(db.String(100), nullable=False)
    input_tokens = db.Column(db.Integer, nullable=False, default=0)
    output_tokens = db.Column(db.Integer, nullable=False, default=0)
    duration_ms = db.Column(db.Integer, nullable=False, default=0)
    succeeded = db.Column(db.Boolean, nullable=False, default=True)
    consultation_id = db.Column(
        db.Integer, db.ForeignKey('consultation.id', ondelete='SET NULL'), nullable=True,
    )
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)


class ConsultationTrial(db.Model):
    """One live trial per account. Starts at the first go-live, no card.

    ``email_key`` is the normalised address, so a second trial from the same
    inbox is refused. ``domain`` is stored for a work address so a run of
    trials from one organisation can be reviewed. It does not block them:
    a university or a publisher can have several buyers.
    """
    __tablename__ = 'consultation_trial'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(
        db.Integer, db.ForeignKey('user.id', ondelete='CASCADE'), nullable=False, unique=True,
    )
    email_key = db.Column(db.String(320), nullable=False, unique=True)
    domain = db.Column(db.String(253), nullable=True, index=True)
    # Campaign source on the link when the trial started, or ``direct``.
    acquisition_source = db.Column(db.String(80), nullable=True)
    started_at = db.Column(db.DateTime, nullable=False)
    ends_at = db.Column(db.DateTime, nullable=False, index=True)
    ending_notified_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)

    user = db.relationship('User', backref=db.backref('consultation_trial', uselist=False, passive_deletes=True))

    @property
    def is_open(self) -> bool:
        return self.ends_at > utcnow_naive()
