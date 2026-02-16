import time
import hmac
import hashlib
import logging
from flask import request, current_app

logger = logging.getLogger(__name__)

HONEYPOT_FIELD = 'website_url'
TIMESTAMP_FIELD = '_ts'
MIN_SUBMIT_SECONDS = 3
MAX_TOKEN_AGE_SECONDS = 7200


def _get_secret():
    secret = current_app.config.get('SECRET_KEY')
    if not secret:
        logger.error("SECRET_KEY is not configured — bot protection signatures are insecure")
        raise RuntimeError("SECRET_KEY must be configured")
    return secret


def generate_form_token():
    ts = str(int(time.time()))
    secret = _get_secret()
    sig = hmac.new(secret.encode(), ts.encode(), hashlib.sha256).hexdigest()[:16]
    return f"{ts}.{sig}"


def check_bot_submission():
    honeypot_value = request.form.get(HONEYPOT_FIELD, '')
    if honeypot_value:
        logger.warning(f"Bot detected (honeypot filled): {request.remote_addr}")
        return True

    ts_token = request.form.get(TIMESTAMP_FIELD, '')
    if not ts_token:
        logger.warning(f"Bot detected (missing timestamp token): {request.remote_addr}")
        return True

    try:
        ts_str, sig = ts_token.split('.', 1)
        secret = _get_secret()
        expected_sig = hmac.new(secret.encode(), ts_str.encode(), hashlib.sha256).hexdigest()[:16]
        if not hmac.compare_digest(sig, expected_sig):
            logger.warning(f"Bot detected (invalid timestamp signature): {request.remote_addr}")
            return True
        elapsed = time.time() - int(ts_str)
        if elapsed < MIN_SUBMIT_SECONDS:
            logger.warning(f"Bot detected (submitted in {elapsed:.1f}s): {request.remote_addr}")
            return True
        if elapsed > MAX_TOKEN_AGE_SECONDS:
            logger.warning(f"Bot detected (stale token, {elapsed:.0f}s old): {request.remote_addr}")
            return True
    except (ValueError, TypeError):
        logger.warning(f"Bot detected (malformed timestamp): {request.remote_addr}")
        return True

    return False
