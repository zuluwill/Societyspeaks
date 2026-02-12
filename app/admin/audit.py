import json
import logging
from sqlalchemy.orm import sessionmaker
from flask import current_app, has_app_context
from app import db
from app.models import AdminAuditEvent

logger = logging.getLogger(__name__)


def write_admin_audit_event(
    *,
    admin_user_id=None,
    action,
    target_type=None,
    target_id=None,
    request_ip=None,
    metadata=None,
):
    """
    Persist an admin audit event using an isolated SQLAlchemy session.

    This avoids committing or rolling back the caller's in-flight transaction.
    Uses db.engine directly to avoid reliance on the caller's scoped session
    bind state, and guards against missing app context.
    """
    if not has_app_context():
        logger.warning(f"Admin audit log skipped (no app context) for {action}")
        return

    metadata = metadata or {}
    audit_session = None
    try:
        engine = db.engine
        session_factory = sessionmaker(bind=engine)
        audit_session = session_factory()
        audit_session.add(
            AdminAuditEvent(
                admin_user_id=admin_user_id,
                action=action,
                target_type=target_type,
                target_id=target_id,
                request_ip=request_ip,
                metadata_json=json.dumps(metadata, default=str),
            )
        )
        audit_session.commit()
    except Exception as exc:
        if audit_session:
            audit_session.rollback()
        current_app.logger.warning(f"Admin audit log failed for {action}: {exc}")
    finally:
        if audit_session:
            audit_session.close()
