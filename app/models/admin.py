"""
Admin-facing models.

AdminAuditEvent logs privileged actions. AdminSettings is a key/value
store for config parameters that admins can change without a deploy.
Moved here from app/models.py as part of the models-split refactor.
Relationships to User use string references.
"""

from app import db
from app.lib.time import utcnow_naive


class AdminAuditEvent(db.Model):
    __table_args__ = (
        db.Index('ix_admin_audit_event_created_at', 'created_at'),
        db.Index('ix_admin_audit_event_admin_user_id', 'admin_user_id'),
        db.Index('ix_admin_audit_event_action', 'action'),
    )

    id = db.Column(db.Integer, primary_key=True)
    admin_user_id = db.Column(db.Integer, db.ForeignKey('user.id', ondelete='SET NULL'), nullable=True)
    action = db.Column(db.String(100), nullable=False)
    target_type = db.Column(db.String(50), nullable=True)
    target_id = db.Column(db.Integer, nullable=True)
    request_ip = db.Column(db.String(64), nullable=True)
    metadata_json = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow_naive, nullable=False)


class AdminSettings(db.Model):
    """
    Key-value store for admin configuration settings.

    Allows adjusting system parameters (like news page quality thresholds)
    without code deployments. Settings can be updated via admin UI.
    """
    __tablename__ = 'admin_settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.JSON, nullable=False)
    updated_at = db.Column(db.DateTime, default=utcnow_naive, onupdate=utcnow_naive)
    updated_by_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Relationships
    updated_by = db.relationship('User', backref='admin_settings')

    @classmethod
    def get(cls, key: str, default=None):
        """Get setting value by key, or return default if not found."""
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default

    @classmethod
    def set(cls, key: str, value, user_id: int = None):
        """Set setting value, creating or updating as needed."""
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_by_id = user_id
        else:
            setting = cls(key=key, value=value, updated_by_id=user_id)
            db.session.add(setting)
        db.session.commit()

    def to_dict(self):
        return {
            'id': self.id,
            'key': self.key,
            'value': self.value,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'updated_by_id': self.updated_by_id
        }

    def __repr__(self):
        return f'<AdminSettings {self.key}>'
