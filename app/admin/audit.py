import json
from sqlalchemy.orm import sessionmaker
from flask import current_app
from app import db
from app.models import AdminAuditEvent


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
    """
    metadata = metadata or {}
    engine = db.session.get_bind()
    session_factory = sessionmaker(bind=engine)
    audit_session = session_factory()
    try:
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
        audit_session.rollback()
        current_app.logger.warning(f"Admin audit log failed for {action}: {exc}")
    finally:
        audit_session.close()
