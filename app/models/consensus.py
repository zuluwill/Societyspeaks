"""
Consensus clustering models.

ConsensusAnalysis caches clustering results (like pol.is's math_main).
ConsensusJob is the persisted queue item that drives the clustering
workers. Moved here from app/models.py as part of the models-split
refactor. Related models (Discussion, User) use string references.
"""

from datetime import timedelta

from sqlalchemy.ext.mutable import MutableDict

from app import db
from app.lib.time import utcnow_naive


def cluster_data_supports_groups(cluster_data) -> bool:
    """The group-structure verdict stored with an analysis (see
    ``assess_group_structure``). No verdict recorded counts as supported."""
    metadata = (cluster_data or {}).get('metadata') or {}
    verdict = metadata.get('group_structure')
    return True if not isinstance(verdict, dict) else bool(verdict.get('supported'))


class ConsensusAnalysis(db.Model):
    """
    Stores clustering results for caching (like pol.is math_main table)
    """
    __tablename__ = 'consensus_analysis'
    __table_args__ = (
        db.Index('idx_consensus_discussion', 'discussion_id'),
    )

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)

    # Clustering results stored as JSON. Wrapped in MutableDict so in-place
    # mutations (e.g. `analysis.cluster_data['ai_summary'] = ...`) are
    # flagged dirty and persisted on commit — otherwise SQLAlchemy sees
    # the same Python object reference and skips the UPDATE.
    cluster_data = db.Column(MutableDict.as_mutable(db.JSON), nullable=False)
    num_clusters = db.Column(db.Integer)
    silhouette_score = db.Column(db.Float)

    # Metadata
    method = db.Column(db.String(50))  # 'pca_kmeans', 'umap_hdbscan', etc.
    participants_count = db.Column(db.Integer)
    statements_count = db.Column(db.Integer)

    created_at = db.Column(db.DateTime, default=utcnow_naive)

    # Relationships
    discussion = db.relationship('Discussion', backref='consensus_analyses')

    @property
    def groups_supported(self) -> bool:
        """Whether the votes showed more grouping than chance would produce.

        Analyses made before the test existed carry no verdict and are
        treated as supported, so historical results are not withdrawn.
        """
        return cluster_data_supports_groups(self.cluster_data)

    @property
    def published_group_count(self) -> int:
        """The number of opinion groups to show or send: none when unsupported."""
        return int(self.num_clusters or 0) if self.groups_supported else 0


class ConsensusJob(db.Model):
    """
    Persisted queue item for consensus computation.

    Supports deduping requests across manual triggers and scheduler sweeps,
    status-based lifecycle tracking, retries, and stale/dead-letter handling.
    """
    __tablename__ = 'consensus_job'
    __table_args__ = (
        db.Index('idx_consensus_job_status_queued_at', 'status', 'queued_at'),
        db.Index('idx_consensus_job_discussion', 'discussion_id', 'created_at'),
        db.Index('idx_consensus_job_dedupe', 'dedupe_key'),
    )

    STATUS_QUEUED = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_STALE = 'stale'
    STATUS_DEAD_LETTER = 'dead_letter'
    ACTIVE_STATUSES = {STATUS_QUEUED, STATUS_RUNNING}

    id = db.Column(db.Integer, primary_key=True)
    discussion_id = db.Column(db.Integer, db.ForeignKey('discussion.id'), nullable=False)
    requested_by_user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    analysis_id = db.Column(db.Integer, db.ForeignKey('consensus_analysis.id'), nullable=True)

    # Stable dedupe key, e.g. discussion + vote-window bucket.
    dedupe_key = db.Column(db.String(255), nullable=False)
    reason = db.Column(db.String(50), nullable=False, default='manual')
    status = db.Column(db.String(20), nullable=False, default=STATUS_QUEUED)

    attempts = db.Column(db.Integer, nullable=False, default=0)
    max_attempts = db.Column(db.Integer, nullable=False, default=3)
    timeout_seconds = db.Column(db.Integer, nullable=False, default=900)
    error_message = db.Column(db.Text, nullable=True)

    queued_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    started_at = db.Column(db.DateTime, nullable=True)
    completed_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive)
    updated_at = db.Column(db.DateTime, nullable=False, default=utcnow_naive, onupdate=utcnow_naive)

    discussion = db.relationship('Discussion', backref='consensus_jobs')
    requested_by = db.relationship('User', backref='consensus_jobs_requested')
    analysis = db.relationship('ConsensusAnalysis', foreign_keys=[analysis_id], backref='consensus_jobs')

    @property
    def is_active(self):
        return self.status in self.ACTIVE_STATUSES

    @property
    def is_timed_out(self):
        if self.status != self.STATUS_RUNNING or not self.started_at:
            return False
        return (utcnow_naive() - self.started_at) > timedelta(seconds=max(0, self.timeout_seconds or 0))
