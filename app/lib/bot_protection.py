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


def check_honeypot_only():
    """True when the hidden honeypot field was filled.

    Use this on long-lived discussion forms where a signed timestamp would
    expire while a page is left open. Full ``check_bot_submission`` still
    applies to short-lived subscribe/register-adjacent flows.
    """
    honeypot_value = request.form.get(HONEYPOT_FIELD, '')
    if honeypot_value:
        logger.warning(f"Bot detected (honeypot filled): {request.remote_addr}")
        return True
    return False


def check_bot_submission():
    if check_honeypot_only():
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


TURNSTILE_VERIFY_URL = 'https://challenges.cloudflare.com/turnstile/v0/siteverify'


def turnstile_is_configured() -> bool:
    try:
        site = (current_app.config.get('TURNSTILE_SITE_KEY') or '').strip()
        secret = (current_app.config.get('TURNSTILE_SECRET_KEY') or '').strip()
    except RuntimeError:
        return False
    return bool(site and secret)


def verify_turnstile_token(token: str | None, remote_ip: str | None = None) -> bool:
    """Verify a Cloudflare Turnstile token. Returns True when Turnstile is unset.

    When keys are configured, missing/invalid tokens fail closed.
    """
    if not turnstile_is_configured():
        return True
    if not token or not str(token).strip():
        logger.warning('Turnstile token missing from submission')
        return False
    secret = current_app.config.get('TURNSTILE_SECRET_KEY')
    try:
        import requests
        payload = {'secret': secret, 'response': token}
        if remote_ip:
            payload['remoteip'] = remote_ip
        resp = requests.post(TURNSTILE_VERIFY_URL, data=payload, timeout=5)
        data = resp.json() if resp.ok else {}
        success = bool(data.get('success'))
        if not success:
            logger.warning('Turnstile verification failed: %s', data.get('error-codes'))
        return success
    except Exception:
        logger.warning('Turnstile verification request failed', exc_info=True)
        return False
