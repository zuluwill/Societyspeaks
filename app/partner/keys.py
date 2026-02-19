import hashlib
import logging
import secrets
from typing import Optional, Tuple

from flask import current_app, after_this_request
from app import db
from app.models import PartnerApiKey, Partner

logger = logging.getLogger(__name__)

KEY_PREFIXES = {
    'test': 'sspk_test_',
    'live': 'sspk_live_',
}


def _get_partner_key_secret() -> str:
    secret = current_app.config.get('PARTNER_KEY_SECRET') or current_app.config.get('SECRET_KEY')
    return str(secret or '')


def hash_partner_api_key(api_key: str) -> str:
    if not api_key:
        raise ValueError("api_key must not be empty")
    secret = _get_partner_key_secret()
    payload = f"{secret}:{api_key}".encode('utf-8')
    return hashlib.sha256(payload).hexdigest()


def generate_partner_api_key(env: str) -> Tuple[str, str, str]:
    if env not in KEY_PREFIXES:
        raise ValueError("env must be 'test' or 'live'")
    token = secrets.token_hex(24)
    full_key = f"{KEY_PREFIXES[env]}{token}"
    key_hash = hash_partner_api_key(full_key)
    key_last4 = full_key[-4:]
    return full_key, key_hash, key_last4


def parse_key_env(api_key: str) -> Optional[str]:
    if not api_key:
        return None
    if api_key.startswith(KEY_PREFIXES['test']):
        return 'test'
    if api_key.startswith(KEY_PREFIXES['live']):
        return 'live'
    return None


def find_partner_api_key(api_key: str):
    """
    Look up and validate a partner API key.

    Returns:
        tuple: (PartnerApiKey record, Partner, env) or (None, None, None)

    Note: Schedules a deferred update to last_used_at via after_this_request,
    so the timestamp is persisted after the response without interfering with
    the caller's transaction.
    """
    if not api_key:
        return None, None, None
    env = parse_key_env(api_key)
    if not env:
        return None, None, None
    key_hash = hash_partner_api_key(api_key)
    record = PartnerApiKey.query.filter_by(key_hash=key_hash, status='active').first()
    if not record:
        return None, None, None
    partner = db.session.get(Partner, record.partner_id)
    if not partner:
        return None, None, None

    # Defer last_used_at update to after the response is sent, avoiding
    # mid-request commits that could interfere with the caller's transaction.
    key_id = record.id
    @after_this_request
    def _update_last_used(response):
        try:
            key_record = db.session.get(PartnerApiKey, key_id)
            if key_record:
                key_record.last_used_at = db.func.now()
                db.session.commit()
        except Exception:
            db.session.rollback()
            logger.debug("Could not update last_used_at for partner API key")
        return response

    return record, partner, env
