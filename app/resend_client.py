"""
Unified Resend Email Client

Handles all email delivery via Resend API:
- Transactional emails (password reset, welcome, account activation)
- Daily question emails (with batch API support for high volume)
- Daily brief emails (already handled by brief/email_client.py)

Replaces Loops.so integration with a single, simpler provider.
"""

import os
import re
import time
import random
import logging
from datetime import datetime
from app.lib.time import utcnow_naive
from typing import List, Dict, Optional, Any, Tuple
from flask import render_template, current_app, url_for
from flask_babel import force_locale, gettext
import requests
from app.email_utils import (  # shared utilities
    RateLimiter,
    extract_clean_email as _extract_clean_email,
    is_reserved_documentation_email,
    partition_email_recipients,
)
from app.briefing.link_tracker import wrap_links as _wrap_links
from app.lib.unsubscribe_tokens import build_question_unsubscribe_url
from app.lib.locale_utils import resolve_user_locale, email_html_locale_kwargs
from app.programmes.journey import GUIDED_JOURNEY_DISPLAY_MINUTES_PER_THEME
from app.lib.email_idempotency import (
    content_fingerprint,
    ensure_email_idempotency,
    scoped_entity_ref,
    send_attempt_entity_ref as _send_attempt_entity_ref,
    token_entity_ref as _token_entity_ref,
    url_token_segment as _url_token_segment,
)

logger = logging.getLogger(__name__)


def _render_for_user(user, template, **ctx) -> str:
    """Render an email template under the user's preferred locale.

    Forces the Flask-Babel locale to `user.language` (or 'en' fallback) so every
    `_()` call inside the template — including any loaded layout/partials — picks
    up the right translations. Works outside request context too.
    """
    locale_str = resolve_user_locale(user)
    with force_locale(locale_str):
        from app.lib.brief_from_email import brief_from_email_for_templates
        base_ctx = email_html_locale_kwargs(locale_str)
        merged = {
            **base_ctx,
            'brief_from_email': brief_from_email_for_templates(),
            **ctx,
        }
        return render_template(template, **merged)


def _subject_for_user(user, message: str, **variables) -> str:
    """Translate an email subject under the user's preferred locale.

    Mirrors `_render_for_user` but for the string we hand to Resend as subject.
    Keeps substitution variables lazy so translators can rearrange placeholders.

    Msgids passed as positional string literals (second argument) are extracted by pybabel
    via ``keywords = _subject_for_user:2`` in ``babel.cfg``.
    Strings that only flow through intermediates such as ``subject_msgid`` or nested
    ``subject=`` callers are duplicated in ``app/email_subject_msgids_for_extract.py`` so
    ``pybabel extract`` still catalogs them — keep that module in sync when changing copy.
    """
    with force_locale(resolve_user_locale(user)):
        return gettext(message, **variables) if variables else gettext(message)



def _email_sending_allowed_for_environment() -> bool:
    """
    Allow outbound email only in deployed production by default.

    Override for intentional non-production testing with:
    ALLOW_EMAIL_IN_NON_PROD=1
    """
    if os.environ.get('ALLOW_EMAIL_IN_NON_PROD') == '1':
        return True
    from app.lib.deployed_env import is_deployed_production

    return is_deployed_production()


_RESEND_API_URL = 'https://api.resend.com/emails'
_RESEND_BATCH_API_URL = 'https://api.resend.com/emails/batch'

_RETRYABLE_ERRORS = (
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    OSError,
    IOError,
)

# 501/505 are protocol-level "this will never work"; everything else in 5xx
# (including Cloudflare 520–527/530 in front of api.resend.com) is transient.
_NON_RETRYABLE_5XX = frozenset({501, 505})
_MAX_RETRY_WAIT_SECONDS = 30.0
_MAX_ERROR_BODY_CHARS = 240
_RE_HTML_TITLE = re.compile(r'<title>\s*([^<]+?)\s*</title>', re.IGNORECASE)
_RE_HTML_TAGS = re.compile(r'<[^>]+>')
_RE_CF_RAY_BODY = re.compile(
    r'Cloudflare Ray ID:\s*(?:<[^>]+>)?([a-f0-9]+)',
    re.IGNORECASE,
)


def is_retryable_http_status(status_code: int) -> bool:
    """True for statuses that are safe (and worth) retrying against Resend.

    Covers 408/429, standard gateway 5xx, and Cloudflare edge 52x pages that
    wrap api.resend.com. Observed in production as HTTP 520 HTML dumps that
    previously failed on the first attempt and waited for hourly catch-up.
    """
    if status_code in (408, 429):
        return True
    if 500 <= status_code <= 599:
        return status_code not in _NON_RETRYABLE_5XX
    return False


def _response_headers(response) -> dict:
    headers = getattr(response, 'headers', None)
    if not headers:
        return {}
    try:
        return dict(headers)
    except Exception:
        return {}


def _header_ci(headers: dict, name: str) -> str:
    want = name.lower()
    for key, value in headers.items():
        if str(key).lower() == want and value is not None:
            return str(value)
    return ''


def compact_resend_error_body(response) -> str:
    """Collapse a Resend/Cloudflare error body into a single log-safe line.

    Cloudflare 520 pages are multi-kilobyte HTML; logging ``response.text``
    verbatim floods Sentry (PYTHON-FLASK-DX) and splits across log lines.
    """
    raw = (getattr(response, 'text', None) or '')[:4000]
    headers = _response_headers(response)
    content_type = _header_ci(headers, 'Content-Type').lower()

    json_fn = getattr(response, 'json', None)
    if callable(json_fn):
        try:
            data = json_fn()
        except Exception:
            data = None
        if isinstance(data, dict):
            err = data.get('error')
            if isinstance(err, dict):
                name = err.get('name') or err.get('type') or data.get('name')
                message = err.get('message') or data.get('message')
            else:
                name = data.get('name') or data.get('type')
                message = data.get('message') or (err if isinstance(err, str) else None)
            parts = [str(p) for p in (name, message) if p]
            if parts:
                return ' — '.join(parts)[:_MAX_ERROR_BODY_CHARS]
            dumped = str(data)
            return dumped[:_MAX_ERROR_BODY_CHARS]

    stripped = raw.lstrip()
    looks_html = (
        'html' in content_type
        or stripped[:15].lower().startswith('<!doctype')
        or stripped[:6].lower().startswith('<html')
    )
    if looks_html:
        title = ''
        match = _RE_HTML_TITLE.search(raw)
        if match:
            title = ' '.join(match.group(1).split())
        ray = _header_ci(headers, 'cf-ray')
        if not ray:
            ray_match = _RE_CF_RAY_BODY.search(raw)
            ray = ray_match.group(1) if ray_match else ''
        bits = [title or 'HTML error page']
        if ray:
            bits.append(f'cf-ray={ray}')
        return ' — '.join(bits)[:_MAX_ERROR_BODY_CHARS]

    text = ' '.join(_RE_HTML_TAGS.sub(' ', raw).split())
    return text[:_MAX_ERROR_BODY_CHARS]


def format_resend_http_error(response) -> str:
    """Canonical ``API error: <status> - <compact body>`` string for callers."""
    status = getattr(response, 'status_code', '?')
    body = compact_resend_error_body(response) or '(empty body)'
    return f'API error: {status} - {body}'


def _retry_wait_seconds(response, attempt: int, retry_delay: float) -> float:
    """Backoff for the next attempt. Honor numeric Retry-After, then exp+jitter.

    Capped so one Cloudflare blip cannot stall a whole brief batch.
    """
    headers = _response_headers(response) if response is not None else {}
    retry_after = _header_ci(headers, 'Retry-After')
    if retry_after:
        try:
            parsed = float(retry_after.strip())
            if parsed >= 0:
                return min(parsed, _MAX_RETRY_WAIT_SECONDS)
        except (TypeError, ValueError):
            pass
    wait = retry_delay * (2 ** attempt)
    wait += wait * 0.25 * random.random()
    return min(wait, _MAX_RETRY_WAIT_SECONDS)


def _log_resend_failure(
    log_prefix: str,
    err: str,
    status_code: Optional[int],
    warn_statuses: frozenset,
    warn_on_retryable: bool,
) -> None:
    warn = False
    if status_code is not None:
        if status_code in warn_statuses:
            warn = True
        elif warn_on_retryable and is_retryable_http_status(status_code):
            warn = True
    (logger.warning if warn else logger.error)(f"{log_prefix}: {err}")


def _resend_http_post(
    api_key: str,
    body: Any,
    url: str,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 30,
    log_prefix: str = "Resend",
    idempotency_key: Optional[str] = None,
    warn_statuses: frozenset = frozenset(),
    warn_on_retryable: bool = False,
) -> Tuple[Optional[requests.Response], Optional[str]]:
    """
    POST to the Resend API with exponential-backoff retry on transient errors.

    Returns (response, None) on HTTP 200, or (None, error_str) on failure.
    Logs all warnings and errors internally.

    Pass idempotency_key for sends that must not be duplicated (e.g. brief emails).
    Resend deduplicates requests with the same Idempotency-Key within a short window.

    ``warn_statuses`` / ``warn_on_retryable`` opt a caller (daily brief) into
    WARNING after a failure that will be retried upstream, so isolated
    Cloudflare 52x blips do not page. Transactional mail keeps ERROR.
    """
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json',
    }
    if idempotency_key:
        headers['Idempotency-Key'] = idempotency_key
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=body, headers=headers, timeout=timeout)
            if response.status_code == 200:
                return response, None
            elif is_retryable_http_status(response.status_code):
                if attempt < max_retries - 1:
                    wait = _retry_wait_seconds(response, attempt, retry_delay)
                    kind = (
                        'rate limited'
                        if response.status_code == 429
                        else f'transient {response.status_code}'
                    )
                    logger.warning(
                        f"{log_prefix} {kind} — waiting {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                err = (
                    f"Rate limited after {max_retries} attempts"
                    if response.status_code == 429
                    else f"Transient {response.status_code} after {max_retries} attempts"
                )
                _log_resend_failure(
                    log_prefix, err, response.status_code,
                    warn_statuses, warn_on_retryable,
                )
                return None, err
            elif response.status_code == 409:
                # Resend distinguishes concurrent (safe to retry) from
                # invalid_idempotent_request (same key, different body — don't retry).
                err_name = ''
                try:
                    err_name = (response.json() or {}).get('name') or ''
                except Exception:
                    err_name = ''
                if err_name == 'concurrent_idempotent_requests' and attempt < max_retries - 1:
                    wait = _retry_wait_seconds(response, attempt, retry_delay)
                    logger.warning(
                        f"{log_prefix} concurrent idempotent request — waiting {wait:.1f}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait)
                    continue
                err = format_resend_http_error(response)
                _log_resend_failure(
                    log_prefix, err, response.status_code,
                    warn_statuses, warn_on_retryable,
                )
                return None, err
            else:
                err = format_resend_http_error(response)
                _log_resend_failure(
                    log_prefix, err, response.status_code,
                    warn_statuses, warn_on_retryable,
                )
                return None, err
        except _RETRYABLE_ERRORS as e:
            if attempt < max_retries - 1:
                wait = _retry_wait_seconds(None, attempt, retry_delay)
                logger.warning(
                    f"{log_prefix} transient error (attempt {attempt + 1}/{max_retries}): "
                    f"{type(e).__name__}: {e} — retrying in {wait:.1f}s"
                )
                time.sleep(wait)
            else:
                err = f"Transient error after {max_retries} attempts: {e}"
                logger.error(f"{log_prefix}: {err}")
                return None, err
        except requests.exceptions.RequestException as e:
            err = f"Request error (non-retryable): {e}"
            logger.error(f"{log_prefix}: {err}")
            return None, err
    return None, "Max retries exceeded"


def _weekly_digest_ref(prefix: str, recipient_id, *content_parts) -> str:
    """Idempotency ref for weekly sends.

    Calendar week + recipient scopes the campaign; ``content_parts`` fingerprint
    the body so Resend never sees the same key with a different payload
    (409 ``invalid_idempotent_request``). Cross-restart "already mailed this
    week" is enforced by DB markers such as ``last_weekly_email_sent``.
    """
    iso_year, iso_week, _ = utcnow_naive().date().isocalendar()
    parts = [f'{iso_year}w{iso_week:02d}', recipient_id]
    if content_parts:
        parts.append(content_fingerprint(content_parts))
    return scoped_entity_ref(prefix, *parts)


def _compact_digest_html(html: str, label: str) -> str:
    """Minify a question-digest email and warn if it will be clipped.

    The daily brief runs its rendered HTML through the same minifier before
    send; the question digests did not, and shipped ~61KB (weekly, 5 questions)
    and more for the 10-question monthly — close to, or past, the ~102KB point
    where Gmail truncates the message and hides the unsubscribe footer behind a
    "View entire message" link.

    Unlike the brief there is nothing safe to auto-trim here: every question is
    the payload. So this compacts what it can and logs loudly when the result
    is still too big, rather than silently dropping content.

    Imported locally: ``app.brief.email_client`` imports ``_render_for_user``
    from this module, so a module-level import would close the cycle.
    """
    from app.brief.email_client import (
        GMAIL_CLIP_LIMIT_BYTES,
        _email_html_byte_size,
        _minify_email_html,
    )

    before = _email_html_byte_size(html)
    try:
        html = _minify_email_html(html)
    except Exception as e:  # never block a send on cosmetics
        logger.warning(f"Minify failed for {label}, sending unminified: {e}")
        return html

    after = _email_html_byte_size(html)
    logger.info(
        "%s minified: %d → %d bytes (Gmail clips ~%d)",
        label, before, after, GMAIL_CLIP_LIMIT_BYTES,
    )
    return html


def _warn_if_clipped(html: str, label: str) -> None:
    """Log when a digest will be clipped by Gmail after link wrapping."""
    from app.brief.email_client import GMAIL_CLIP_LIMIT_BYTES, _email_html_byte_size

    size = _email_html_byte_size(html)
    if size > GMAIL_CLIP_LIMIT_BYTES:
        logger.warning(
            "%s is %d bytes after click-tracking wrap (Gmail clips ~%d); "
            "recipients will see a truncated message with the unsubscribe "
            "footer hidden — reduce questions per digest or trim per-question copy",
            label, size, GMAIL_CLIP_LIMIT_BYTES,
        )


def resend_post_with_retry(
    api_key: str,
    payload: dict,
    url: str = _RESEND_API_URL,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 30,
    idempotency_key: Optional[str] = None,
    warn_statuses: frozenset = frozenset(),
    warn_on_retryable: bool = False,
) -> Tuple[bool, Optional[str]]:
    """
    POST a single email to the Resend API with exponential-backoff retry.

    Retries on transient OS/network errors (OSError/IOError/Timeout/ConnectionError)
    that can occur when TLS certificate files are read from the overlay filesystem.
    Also retries on 408, 429, and 5xx except 501/505 — including Cloudflare 52x
    in front of api.resend.com.

    Pass idempotency_key for sends that must not be duplicated on retry.
    Resend deduplicates requests with the same Idempotency-Key within a short window,
    so a retried 504 that was actually accepted will not produce a duplicate email.

    Returns:
        (success, message_id)  — message_id is None on failure or if Resend omits it.
        Reserved documentation domains (example.com, …) are stripped before
        the HTTP call; if none remain, this is a successful no-op.
    """
    deliverable, reserved = partition_email_recipients(payload.get("to") or [])
    if reserved:
        logger.warning(
            "Skipping reserved documentation address(es) before Resend: %s",
            reserved,
        )
    if not deliverable:
        return True, None
    if reserved:
        payload = {**payload, "to": deliverable}

    response, err = _resend_http_post(
        api_key, payload, url, max_retries, retry_delay, timeout,
        idempotency_key=idempotency_key,
        warn_statuses=warn_statuses,
        warn_on_retryable=warn_on_retryable,
    )
    if response is None:
        return False, err
    try:
        message_id = response.json().get('id')
    except Exception:
        message_id = None
    return True, message_id


def resend_batch_with_retry(
    api_key: str,
    payloads: list,
    url: str = _RESEND_BATCH_API_URL,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: int = 60,
    idempotency_key: Optional[str] = None,
) -> Tuple[bool, int, int, List[str]]:
    """
    POST a batch of emails to the Resend batch API with exponential-backoff retry.

    Pass idempotency_key so a retried 5xx/timeout that Resend actually accepted
    cannot deliver the whole batch twice.

    Returns:
        (success, sent_count, failed_count, errors, failed_indices)

    failed_indices are positions in ``payloads`` that Resend reported as
    failed. It may be shorter than failed_count when Resend returns errors
    without an index — callers must not assume every failure is attributed.
    """
    all_failed = list(range(len(payloads or [])))
    filtered = []
    for payload in payloads or []:
        deliverable, reserved = partition_email_recipients(payload.get("to") or [])
        if reserved:
            logger.warning(
                "Batch: skipping reserved documentation address(es): %s",
                reserved,
            )
        if not deliverable:
            continue
        filtered.append({**payload, "to": deliverable} if reserved else payload)
    if not filtered:
        return True, 0, 0, [], []

    response, error = _resend_http_post(
        api_key, filtered, url, max_retries, retry_delay, timeout,
        log_prefix="Resend batch", idempotency_key=idempotency_key,
    )
    if response is None:
        return False, 0, len(payloads or []), [error or "Unknown error"], all_failed

    try:
        data = response.json() or {}
    except Exception as e:
        return False, 0, len(payloads or []), [f"Invalid JSON response from Resend batch API: {e}"], all_failed

    created = data.get("data") or []
    raw_errors = data.get("errors") or []

    sent_count = len(created)
    failed_count = len(raw_errors)

    # If Resend returns no structured errors, treat the call as fully successful.
    # This matches strict validation mode (atomic success) responses.
    errors: List[str] = []
    failed_indices: List[int] = []
    for err in raw_errors:
        if isinstance(err, dict):
            idx = err.get("index")
            msg = err.get("message") or err.get("error") or str(err)
            if isinstance(idx, int):
                failed_indices.append(idx)
                errors.append(f"[{idx}] {msg}")
            else:
                errors.append(msg)
        else:
            errors.append(str(err))

    # If we received neither data nor errors, fall back to optimistic "all sent"
    # but preserve any top-level error fields if present.
    if sent_count == 0 and failed_count == 0:
        sent_count = len(payloads or [])

    success = failed_count == 0
    return success, sent_count, failed_count, errors, failed_indices


class ResendEmailClient:
    """
    Unified Resend client for all transactional and batch emails.

    Features:
    - Single email sends for transactional (password reset, welcome)
    - Batch API for high-volume sends (daily questions)
    - Rate limiting (14 emails/sec for single, batched requests for bulk)
    - Retry logic with exponential backoff
    - Jinja2 template rendering
    """

    RATE_LIMIT = 14  # emails per second for single sends
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds
    BATCH_SIZE = 100  # Resend allows up to 100 emails per batch request

    def __init__(self):
        self.api_key = os.environ.get('RESEND_API_KEY')
        self._disabled = False
        self.last_message_id: Optional[str] = None
        self.last_send_error: Optional[str] = None
        self._email_allowed = _email_sending_allowed_for_environment()

        if not self._email_allowed:
            logger.warning(
                "Outbound email disabled outside deployed production. "
                "Set ALLOW_EMAIL_IN_NON_PROD=1 only for intentional testing."
            )
            self._disabled = True
        
        if not self.api_key:
            # Graceful degradation in non-production or when email sending is intentionally disabled.
            flask_env = os.environ.get('FLASK_ENV', 'production')
            if (not self._email_allowed) or flask_env in ('development', 'testing'):
                logger.warning(
                    "RESEND_API_KEY not set - email sending disabled. "
                    "Set RESEND_API_KEY in your .env file to enable emails."
                )
                self._disabled = True
            else:
                raise ValueError("RESEND_API_KEY environment variable required in production")

        self.rate_limiter = RateLimiter(self.RATE_LIMIT)

        # Email addresses - use brief.societyspeaks.io subdomain which is verified in Resend
        self.from_email = os.environ.get('RESEND_FROM_EMAIL', 'Society Speaks <hello@brief.societyspeaks.io>')
        self.from_email_daily = os.environ.get('RESEND_DAILY_FROM_EMAIL', 'Daily Questions <daily@brief.societyspeaks.io>')

        # Separate From for transactional (auth) emails. Ideally this is on the
        # root domain (`societyspeaks.io`) so the sender↔link domain match;
        # Gmail Safe Browsing treats mismatched domains as a phishing signal
        # and marks the link as "dangerous". Falls back to RESEND_FROM_EMAIL
        # while DKIM/DMARC on the root domain is still being configured.
        _tx_from = (os.environ.get('RESEND_TRANSACTIONAL_FROM_EMAIL') or '').strip()
        self.transactional_from_email = _tx_from if _tx_from else self.from_email

        # Optional Reply-To for transactional mail — a reachable Reply-To is a
        # positive deliverability signal and gives users a way to respond.
        _reply = (os.environ.get('RESEND_REPLY_TO') or '').strip()
        self.reply_to_email = _reply if _reply else None

        # Base URL for building links
        self.base_url = os.environ.get('BASE_URL', 'https://societyspeaks.io')

    def _send_with_retry(
        self,
        email_data: Dict[str, Any],
        use_rate_limit: bool = True,
        idempotency_key: Optional[str] = None,
    ) -> bool:
        """
        Send a single email via Resend with rate limiting and retry.

        Always attaches a Resend Idempotency-Key (via ``X-Entity-Ref-ID``):
        explicit key / existing header if present, otherwise a per-attempt UUID.
        Call sites that omit a key still get HTTP-retry safety without 409 risk
        on later unrelated sends.

        Args:
            email_data: Email payload for Resend API
            use_rate_limit: Whether to apply rate limiting (default True)
            idempotency_key: Optional explicit key (overrides header)

        Returns:
            bool: True on success, False on failure
        """
        if self._disabled:
            logger.info(f"Email skipped (disabled): {email_data.get('to', ['unknown'])[0]}")
            self.last_message_id = None
            return True

        # Validate and normalise the 'to' addresses before sending.
        # Resend rejects bare angle-bracket addresses like <user@domain.com> with
        # a 422 validation_error; catching them here prevents avoidable API round-trips.
        raw_to = email_data.get('to') or []
        cleaned_to = []
        skipped_reserved = []
        for raw_addr in raw_to:
            clean = _extract_clean_email(raw_addr)
            if clean is None:
                logger.error(
                    f"Skipping email send — invalid 'to' address: {repr(raw_addr)}"
                )
                self.last_message_id = None
                return False
            if is_reserved_documentation_email(clean):
                skipped_reserved.append(clean)
                continue
            cleaned_to.append(clean)
        if skipped_reserved:
            logger.warning(
                "Skipping reserved documentation address(es): %s",
                skipped_reserved,
            )
        if not cleaned_to:
            self.last_message_id = None
            self.last_send_error = None
            return True
        email_data = {**email_data, 'to': cleaned_to}
        email_data, resolved_key = ensure_email_idempotency(
            email_data, idempotency_key=idempotency_key
        )

        if use_rate_limit:
            self.rate_limiter.acquire()

        success, result = resend_post_with_retry(
            self.api_key,
            email_data,
            max_retries=self.MAX_RETRIES,
            retry_delay=self.RETRY_DELAY,
            idempotency_key=resolved_key,
        )
        if success:
            self.last_message_id = result
            self.last_send_error = None
        else:
            self.last_message_id = None
            self.last_send_error = result
        return success

    def _send_batch(
        self,
        emails: List[Dict[str, Any]],
        idempotency_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Send a batch of emails via the Resend Batch API.

        Args:
            emails: List of email payloads (max 100 per Resend limit)
            idempotency_key: Stable key so an HTTP retry cannot double-send the batch

        Returns:
            dict: {'sent': count, 'failed': count, 'errors': list,
                   'failed_indices': positions in ``emails`` known to have failed}

            failed_indices may undercount when Resend reports failures without
            attributing them to a payload — check 'failed' vs len(failed_indices).
        """
        results: Dict[str, Any] = {'sent': 0, 'failed': 0, 'errors': [], 'failed_indices': []}

        if not emails:
            return results

        if self._disabled:
            logger.info(f"Batch of {len(emails)} emails skipped (disabled)")
            results['sent'] = len(emails)
            return results

        # Validate and normalise each payload's 'to' field before sending.
        # valid_indices maps each entry of valid_emails back to its position
        # in the caller's list so failures land on the right recipient.
        valid_emails = []
        valid_indices = []
        for original_index, payload in enumerate(emails):
            raw_to = payload.get('to') or []
            cleaned_to = []
            all_valid = True
            skipped_reserved = []
            for raw_addr in raw_to:
                clean = _extract_clean_email(raw_addr)
                if clean is None:
                    logger.error(f"Batch: dropping email with invalid 'to' address: {repr(raw_addr)}")
                    results['failed'] += 1
                    results['errors'].append(f"Invalid address: {repr(raw_addr)}")
                    results['failed_indices'].append(original_index)
                    all_valid = False
                    break
                if is_reserved_documentation_email(clean):
                    skipped_reserved.append(clean)
                    continue
                cleaned_to.append(clean)
            if skipped_reserved:
                logger.warning(
                    "Batch: skipping reserved documentation address(es): %s",
                    skipped_reserved,
                )
            if all_valid and cleaned_to:
                valid_emails.append({**payload, 'to': cleaned_to})
                valid_indices.append(original_index)

        if not valid_emails:
            return results

        if len(valid_emails) > self.BATCH_SIZE:
            raise ValueError(f"Batch size {len(valid_emails)} exceeds maximum {self.BATCH_SIZE}")

        success, sent_count, failed_count, errors, failed_positions = resend_batch_with_retry(
            self.api_key,
            valid_emails,
            max_retries=self.MAX_RETRIES,
            retry_delay=self.RETRY_DELAY,
            idempotency_key=idempotency_key,
        )
        results['sent'] += sent_count
        if not success:
            results['failed'] += failed_count or (len(valid_emails) - sent_count)
            results['errors'].extend(errors)
            results['failed_indices'].extend(
                valid_indices[pos] for pos in failed_positions if 0 <= pos < len(valid_indices)
            )
        return results

    # =========================================================================
    # TRANSACTIONAL EMAILS
    # =========================================================================

    def _send_transactional_email(
        self,
        user,
        *,
        template_stem: str,
        subject_msgid: str,
        entity_ref_id: Optional[str] = None,
        log_label: str = 'transactional',
        **template_ctx,
    ) -> bool:
        """Render html + plaintext for a transactional email and send via Resend.

        Shared path for password reset, magic login, welcome, verification, and
        account activation emails. Gmail penalises HTML-only transactional mail, so we always
        render the parallel ``{stem}.txt`` template and attach it as the
        ``text`` part of the multipart payload. Also attaches:

        - Reply-To (when ``RESEND_REPLY_TO`` is configured) — positive
          deliverability signal, gives users a place to actually reply.
        - X-Entity-Ref-ID — per-send identifier ESPs can use to dedup
          retried deliveries of the same logical email.
        - transactional_from_email — separate From address configurable via
          ``RESEND_TRANSACTIONAL_FROM_EMAIL`` for sender↔link domain alignment.
        """
        try:
            html = _render_for_user(user, f'{template_stem}.html', **template_ctx)
            text = _render_for_user(user, f'{template_stem}.txt', **template_ctx)
        except Exception as e:
            logger.error(f"Template rendering failed for {template_stem}: {e}")
            return False

        email_data: Dict[str, Any] = {
            'from': self.transactional_from_email,
            'to': [user.email],
            'subject': _subject_for_user(user, subject_msgid),
            'html': html,
            'text': text,
        }
        if self.reply_to_email:
            email_data['reply_to'] = self.reply_to_email

        headers: Dict[str, str] = {}
        if entity_ref_id:
            headers['X-Entity-Ref-ID'] = entity_ref_id
        if headers:
            email_data['headers'] = headers

        success = self._send_with_retry(email_data, use_rate_limit=False)

        if success:
            logger.info(f"{log_label} email sent to user {user.id}")
        else:
            logger.error(f"Failed to send {log_label} email to user {user.id}")

        return success

    def send_password_reset(self, user, token: str) -> bool:
        """Send password reset email."""
        reset_url = f"{self.base_url}/auth/reset-password/{token}"
        return self._send_transactional_email(
            user,
            template_stem='emails/password_reset',
            subject_msgid='Reset Your Password - Society Speaks',
            # Reset tokens are deterministic per user — per-attempt key required.
            entity_ref_id=_send_attempt_entity_ref('password-reset', user.id),
            log_label='Password reset',
            username=user.username or 'User',
            reset_url=reset_url,
            base_url=self.base_url,
        )

    def send_magic_login_link(self, user, magic_url: str, *, submitted_email: str = None) -> bool:
        """Send a magic-link sign-in email.

        The URL points at the landing page (GET), which shows a Continue button
        that POSTs to consume the token — defeats email-scanner prefetchers
        that would otherwise burn a one-shot token before the user clicks.
        """
        from app.lib.user_display import friendly_display_name

        token = _url_token_segment(magic_url)
        greeting_name = friendly_display_name(user, submitted_email=submitted_email)
        return self._send_transactional_email(
            user,
            template_stem='emails/magic_login',
            subject_msgid='Your Society Speaks sign-in link',
            entity_ref_id=_token_entity_ref('magic-login', user.id, token),
            log_label='Magic-login',
            username=greeting_name,
            magic_url=magic_url,
            base_url=self.base_url,
        )

    def send_welcome_email(self, user, verification_url: Optional[str] = None) -> bool:
        """Send welcome email to new user."""
        return self._send_transactional_email(
            user,
            template_stem='emails/welcome',
            subject_msgid='Welcome to Society Speaks!',
            entity_ref_id=_send_attempt_entity_ref('welcome', user.id),
            log_label='Welcome',
            username=user.username or 'There',
            verification_url=verification_url,
            base_url=self.base_url,
        )

    def send_verification_email(self, user, verification_url: str) -> bool:
        """Send a standalone email verification email (used for resends)."""
        return self._send_transactional_email(
            user,
            template_stem='emails/verify_email',
            subject_msgid='Verify your Society Speaks email address',
            # Verify tokens dump only user_id — deterministic; per-attempt key.
            entity_ref_id=_send_attempt_entity_ref('verify', user.id),
            log_label='Verification',
            username=user.username or 'there',
            verification_url=verification_url,
            base_url=self.base_url,
        )

    def send_account_activation(self, user, activation_token: str) -> bool:
        """
        Send account activation email.

        Args:
            user: User object with email and username
            activation_token: Activation token

        Returns:
            bool: Success status
        """
        activation_url = f"{self.base_url}/auth/activate/{activation_token}"
        return self._send_transactional_email(
            user,
            template_stem='emails/account_activation',
            subject_msgid='Activate Your Society Speaks Account',
            entity_ref_id=_send_attempt_entity_ref('activate', user.id),
            log_label='Account activation',
            username=user.username or 'User',
            activation_url=activation_url,
            base_url=self.base_url,
        )

    # =========================================================================
    # DAILY QUESTION EMAILS
    # =========================================================================

    def send_daily_question_welcome(self, subscriber) -> bool:
        """
        Send welcome email to new daily question subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object

        Returns:
            bool: Success status
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        daily_question_url = f"{self.base_url}/daily"
        unsubscribe_url = build_question_unsubscribe_url(self.base_url, subscriber)
        
        try:
            # Build preferences URL for managing frequency
            preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
            
            html = _render_for_user(
                subscriber,
                'emails/daily_question_welcome.html',
                magic_link_url=magic_link_url,
                daily_question_url=daily_question_url,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for daily_question_welcome: {e}")
            return False

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': _subject_for_user(subscriber, "You're Subscribed to Daily Civic Questions!"),
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                'X-Entity-Ref-ID': _send_attempt_entity_ref(
                    'daily-question-welcome', subscriber.id
                ),
            }
        }

        success = self._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Daily question welcome email sent to {subscriber.email}")
        else:
            logger.error(f"Failed to send daily question welcome email to {subscriber.email}")

        return success

    def _build_vote_urls(self, subscriber, question_id: int) -> dict:
        """
        Build question-specific one-click vote URLs.
        
        DRY helper method used by both single and batch email sending.

        Args:
            subscriber: DailyQuestionSubscriber with generate_vote_token method
            question_id: The daily question ID to bind the token to

        Returns:
            dict with 'agree', 'disagree', 'unsure' URLs
        """
        vote_token = subscriber.generate_vote_token(question_id)
        return {
            'agree': f"{self.base_url}/daily/v/{vote_token}/agree",
            'disagree': f"{self.base_url}/daily/v/{vote_token}/disagree",
            'unsure': f"{self.base_url}/daily/v/{vote_token}/unsure",
        }

    def send_daily_question(self, subscriber, question) -> bool:
        """
        Send daily question email to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            question: DailyQuestion object

        Returns:
            bool: Success status
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        question_url = f"{self.base_url}/daily/{question.question_date.isoformat()}"
        unsubscribe_url = build_question_unsubscribe_url(self.base_url, subscriber)
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"

        # Generate question-specific vote URLs using helper
        vote_urls = self._build_vote_urls(subscriber, question.id)

        # Build streak message
        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."

        try:
            from app.daily.utils import get_source_articles_for_question, get_brief_context_for_question
            source_articles = get_source_articles_for_question(question, limit=3)
            brief_context = get_brief_context_for_question(question, base_url=self.base_url)
        except Exception:
            source_articles = []
            brief_context = None
        
        try:
            html = _render_for_user(
                subscriber,
                'emails/daily_question.html',
                question_number=question.question_number,
                question_text=question.question_text,
                question_context=question.context or "",
                why_this_question=why_this,
                topic_category=question.topic_category or "Civic",
                magic_link_url=magic_link_url,
                question_url=question_url,
                streak_message=streak_message,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
                vote_agree_url=vote_urls['agree'],
                vote_disagree_url=vote_urls['disagree'],
                vote_unsure_url=vote_urls['unsure'],
                base_url=self.base_url,
                source_articles=source_articles,
                brief_context=brief_context,
            )
        except Exception as e:
            logger.error(f"Template rendering failed for daily_question: {e}")
            return False

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=question.id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': _subject_for_user(subscriber, 'Daily Question #%(num)s: %(topic)s', num=question.question_number, topic=question.topic_category or _subject_for_user(subscriber, 'Civic')),
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
            }
        }

        success = self._send_with_retry(email_data)

        if success:
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                    question_subscriber_id=subscriber.id,
                    daily_question_id=question.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

        return success

    def send_weekly_questions_digest(self, subscriber, questions) -> bool:
        """
        Send weekly digest email with 5 questions to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            questions: List of DailyQuestion objects (up to 5)

        Returns:
            bool: Success status
        """
        from app.daily.utils import get_discussion_stats_for_question

        if not questions:
            logger.warning(f"No questions provided for weekly digest to {subscriber.email}")
            return False

        # Build URLs with question IDs for batch page
        question_ids = ','.join(str(q.id) for q in questions)
        batch_url = f"{self.base_url}/daily/weekly?token={subscriber.magic_token}&questions={question_ids}"
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
        unsubscribe_url = build_question_unsubscribe_url(self.base_url, subscriber)

        # Build question data with vote URLs, discussion stats, and source articles
        from app.daily.utils import build_question_email_data
        
        questions_data = []
        for question in questions:
            # Use DRY helper function to build all question data (with base_url for email context)
            q_data = build_question_email_data(question, subscriber, base_url=self.base_url)
            questions_data.append(q_data)

        # Get send day name for footer
        send_day_name = subscriber.get_send_day_name()
        send_hour = subscriber.preferred_send_hour

        try:
            html = _render_for_user(
                subscriber,
                'emails/weekly_questions_digest.html',
                questions=questions_data,
                batch_url=batch_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                send_day_name=send_day_name,
                send_hour=send_hour,
                base_url=self.base_url
            )
        except Exception as e:
            logger.error(f"Template rendering failed for weekly_questions_digest: {e}")
            return False

        html = _compact_digest_html(html, 'Weekly questions digest')

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=questions[0].id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )
        _warn_if_clipped(html, 'Weekly questions digest')

        # Build subject line
        first_question = questions[0].question_text[:50]
        subject = _subject_for_user(subscriber, '5 Questions This Week: %(first)s...', first=first_question)

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': subject,
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Idempotency-Key: week + subscriber + question-id fingerprint so
                # key always matches this body. DB last_weekly_email_sent guards
                # cross-restart "already sent this week".
                'X-Entity-Ref-ID': _weekly_digest_ref(
                    'weekly-digest',
                    subscriber.id,
                    *(q.id for q in questions),
                ),
            }
        }

        success = self._send_with_retry(email_data)

        if success:
            subscriber.last_weekly_email_sent = utcnow_naive()
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=subject,
                    question_subscriber_id=subscriber.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

        return success

    def send_monthly_questions_digest(self, subscriber, questions) -> bool:
        """
        Send monthly digest email with 10 questions to a single subscriber.

        Args:
            subscriber: DailyQuestionSubscriber object (must have magic_token set)
            questions: List of DailyQuestion objects (up to 10)

        Returns:
            bool: Success status
        """
        from app.daily.utils import get_discussion_stats_for_question

        if not questions:
            logger.warning(f"No questions provided for monthly digest to {subscriber.email}")
            return False

        # Build URLs with question IDs for batch page
        question_ids = ','.join(str(q.id) for q in questions)
        batch_url = f"{self.base_url}/daily/weekly?token={subscriber.magic_token}&questions={question_ids}"
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"
        unsubscribe_url = build_question_unsubscribe_url(self.base_url, subscriber)

        # Build question data with vote URLs, discussion stats, and source articles
        from app.daily.utils import build_question_email_data
        
        questions_data = []
        for question in questions:
            # Use DRY helper function to build all question data (with base_url for email context)
            q_data = build_question_email_data(question, subscriber, base_url=self.base_url)
            questions_data.append(q_data)

        try:
            # Reuse weekly digest template but with different title
            html = _render_for_user(
                subscriber,
                'emails/weekly_questions_digest.html',
                questions=questions_data,
                batch_url=batch_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                send_day_name='Monthly',
                send_hour=9,
                base_url=self.base_url,
                is_monthly=True
            )
        except Exception as e:
            logger.error(f"Template rendering failed for monthly_questions_digest: {e}")
            return False

        html = _compact_digest_html(html, 'Monthly questions digest')

        secret = current_app.config.get('SECRET_KEY', '')
        html = _wrap_links(
            html=html,
            base_url=self.base_url,
            run_id=questions[0].id,
            r_hash=str(subscriber.id),
            secret=secret,
            track_path='/daily/track/click',
        )
        _warn_if_clipped(html, 'Monthly questions digest')

        # Build subject line
        first_question = questions[0].question_text[:50]
        subject = _subject_for_user(subscriber, '10 Questions This Month: %(first)s...', first=first_question)

        email_data = {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': subject,
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Idempotency-Key: month + subscriber + question-id fingerprint.
                # DB last_monthly_email_sent guards cross-restart duplicates.
                'X-Entity-Ref-ID': scoped_entity_ref(
                    'monthly-digest',
                    f'{utcnow_naive():%Y-%m}',
                    subscriber.id,
                    content_fingerprint(q.id for q in questions),
                ),
            }
        }

        success = self._send_with_retry(email_data)

        if success:
            subscriber.last_monthly_email_sent = utcnow_naive()
            subscriber.last_email_sent = utcnow_naive()
            
            # Record analytics event
            try:
                from app.lib.email_analytics import EmailAnalytics
                EmailAnalytics.record_send(
                    email=subscriber.email,
                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                    subject=subject,
                    question_subscriber_id=subscriber.id
                )
            except Exception as analytics_error:
                logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

        return success

    def _build_daily_question_email(self, subscriber, question) -> Dict[str, Any]:
        """
        Build email payload for a daily question (used in batch sending).

        Args:
            subscriber: DailyQuestionSubscriber with magic_token
            question: DailyQuestion object

        Returns:
            dict: Email payload for Resend API
        """
        magic_link_url = f"{self.base_url}/daily/m/{subscriber.magic_token}"
        question_url = f"{self.base_url}/daily/{question.question_date.isoformat()}"
        unsubscribe_url = build_question_unsubscribe_url(self.base_url, subscriber)
        preferences_url = f"{self.base_url}/daily/preferences?token={subscriber.magic_token}"

        # Generate question-specific vote URLs using helper (DRY)
        vote_urls = self._build_vote_urls(subscriber, question.id)

        streak_message = ""
        if subscriber.current_streak > 1:
            streak_message = f"You've participated {subscriber.current_streak} days in a row!"

        why_this = question.why_this_question or "This question helps us understand how the public thinks about important issues."

        try:
            from app.daily.utils import get_source_articles_for_question, get_brief_context_for_question
            source_articles = get_source_articles_for_question(question, limit=3)
            brief_context = get_brief_context_for_question(question, base_url=self.base_url)
        except Exception:
            source_articles = []
            brief_context = None
        
        html = _render_for_user(
            subscriber,
            'emails/daily_question.html',
            question_number=question.question_number,
            question_text=question.question_text,
            question_context=question.context or "",
            why_this_question=why_this,
            topic_category=question.topic_category or "Civic",
            magic_link_url=magic_link_url,
            question_url=question_url,
            streak_message=streak_message,
            unsubscribe_url=unsubscribe_url,
            preferences_url=preferences_url,
            vote_agree_url=vote_urls['agree'],
            vote_disagree_url=vote_urls['disagree'],
            vote_unsure_url=vote_urls['unsure'],
            base_url=self.base_url,
            source_articles=source_articles,
            brief_context=brief_context,
        )

        return {
            'from': self.from_email_daily,
            'to': [subscriber.email],
            'subject': _subject_for_user(subscriber, 'Daily Question #%(num)s: %(topic)s', num=question.question_number, topic=question.topic_category or _subject_for_user(subscriber, 'Civic')),
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Doubles as the Idempotency-Key on individual-send fallback,
                # so a retried 5xx cannot deliver twice.
                'X-Entity-Ref-ID': scoped_entity_ref(
                    'daily-question', question.id, subscriber.id
                ),
            }
        }

    def send_daily_question_batch(
        self,
        subscribers: List,
        question,
        on_progress: Optional[callable] = None
    ) -> Dict[str, Any]:
        """
        Send daily question to multiple subscribers using batch API.

        Processes subscribers in batches of 100 for efficiency.
        Much faster than individual sends (1 API call per 100 vs 100 calls).

        Args:
            subscribers: List of DailyQuestionSubscriber objects (must have magic_tokens set)
            question: DailyQuestion object
            on_progress: Optional callback(sent, failed, total) for progress updates

        Returns:
            dict: {'sent': int, 'failed': int, 'errors': list, 'failed_emails': list}
        """
        from app import db

        results = {
            'sent': 0,
            'failed': 0,
            'errors': [],
            'failed_emails': []
        }

        if not subscribers:
            return results

        total = len(subscribers)
        processed = 0

        # Process in batches
        for i in range(0, total, self.BATCH_SIZE):
            batch_subscribers = subscribers[i:i + self.BATCH_SIZE]
            batch_emails = []
            # Kept parallel to batch_emails so send results map back to the
            # right subscriber even when some payload builds fail.
            built_subscribers = []

            for subscriber in batch_subscribers:
                try:
                    email_payload = self._build_daily_question_email(subscriber, question)
                    batch_emails.append(email_payload)
                    built_subscribers.append(subscriber)
                except Exception as e:
                    logger.error(f"Failed to build email for {subscriber.email}: {e}")
                    results['failed'] += 1
                    results['failed_emails'].append(subscriber.email)

            if batch_emails:
                # Stable per-batch key: fingerprint subscribers whose payloads
                # actually built, so key and request body always match.
                # (Cross-restart protection comes from the per-batch commit
                # below, not from this key.)
                batch_fingerprint = content_fingerprint(s.id for s in built_subscribers)
                batch_result = self._send_batch(
                    batch_emails,
                    idempotency_key=scoped_entity_ref(
                        'daily-question', question.id, batch_fingerprint
                    ),
                )

                batch_errors = batch_result.get('errors', [])
                is_validation_failure = (
                    batch_result['sent'] == 0
                    and batch_result['failed'] > 0
                    and any('422' in str(e) for e in batch_errors)
                )

                if is_validation_failure:
                    # Batch rejected by Resend due to a bad address (422).
                    # Resend doesn't say which one, so fall back to individual sends.
                    # Any address that also fails individually is invalid — deactivate
                    # it so it never blocks future batches again.
                    logger.warning(
                        f"Batch rejected with 422 (bad address in batch of {len(batch_emails)}); "
                        f"falling back to individual sends to identify the invalid address."
                    )
                    individual_sent = 0
                    individual_failed = 0
                    for sub, payload in zip(built_subscribers, batch_emails):
                        ok = self._send_with_retry(payload, use_rate_limit=True)
                        if ok:
                            individual_sent += 1
                            sub.last_email_sent = utcnow_naive()
                            try:
                                from app.lib.email_analytics import EmailAnalytics
                                EmailAnalytics.record_send(
                                    email=sub.email,
                                    category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                                    subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                                    question_subscriber_id=sub.id,
                                    daily_question_id=question.id
                                )
                            except Exception as analytics_error:
                                logger.warning(f"Failed to record analytics for {sub.email}: {analytics_error}")
                        else:
                            individual_failed += 1
                            # Permanently deactivate — bad address that blocks everyone else.
                            try:
                                sub.is_active = False
                                sub.unsubscribe_reason = 'invalid_email'
                                sub.unsubscribed_at = utcnow_naive()
                                logger.warning(
                                    f"Deactivated subscriber {sub.id} <{sub.email}> — "
                                    f"individual send failed after batch 422; address is invalid."
                                )
                            except Exception as deactivate_err:
                                logger.error(f"Failed to deactivate subscriber {sub.id}: {deactivate_err}")
                    results['sent'] += individual_sent
                    results['failed'] += individual_failed
                    results['errors'].extend(batch_errors)
                else:
                    results['sent'] += batch_result['sent']
                    results['failed'] += batch_result['failed']
                    results['errors'].extend(batch_errors)

                # Update last_email_sent for successful batch sends.
                # batch_emails was built in lockstep with built_subscribers, so
                # failed_indices from _send_batch map straight onto it. Failures
                # Resend did not attribute to a payload stay marked as sent:
                # re-sending ~100 people on the next run is worse than one
                # missed email, and the failure is still logged/counted.
                if batch_result['sent'] > 0:
                    failed_indices = set(batch_result.get('failed_indices') or [])
                    if batch_result['failed'] > len(failed_indices):
                        logger.warning(
                            f"Batch reported {batch_result['failed']} failure(s) but only "
                            f"{len(failed_indices)} attributed to a recipient — "
                            f"unattributed failures will not be retried."
                        )
                    for subscriber_index, subscriber in enumerate(built_subscribers):
                        if subscriber_index in failed_indices:
                            results['failed_emails'].append(subscriber.email)
                            continue
                        subscriber.last_email_sent = utcnow_naive()

                        # Record analytics event for each successful send
                        try:
                            from app.lib.email_analytics import EmailAnalytics
                            EmailAnalytics.record_send(
                                email=subscriber.email,
                                category=EmailAnalytics.CATEGORY_DAILY_QUESTION,
                                subject=f"Daily Question #{question.question_number}: {question.topic_category or 'Civic'}",
                                question_subscriber_id=subscriber.id,
                                daily_question_id=question.id
                            )
                        except Exception as analytics_error:
                            logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")

            # Commit per batch: if the process dies mid-run (deploy, crash),
            # subscribers already mailed keep their last_email_sent marker and
            # the restarted job's filter skips them instead of re-sending.
            try:
                db.session.commit()
            except Exception as e:
                logger.error(f"Failed to commit batch send markers: {e}")
                db.session.rollback()

            processed += len(batch_subscribers)

            if on_progress:
                on_progress(results['sent'], results['failed'], total)

            logger.info(
                f"Batch {i // self.BATCH_SIZE + 1}: "
                f"{results['sent']} sent, {results['failed']} failed of {total}"
            )

        return results


# =============================================================================
# CONVENIENCE FUNCTIONS (drop-in replacements for email_utils.py functions)
# =============================================================================

def get_resend_client() -> ResendEmailClient:
    """Get or create ResendEmailClient instance"""
    return ResendEmailClient()


def send_password_reset_email(user, token: str) -> bool:
    """
    Send password reset email via Resend.
    Drop-in replacement for email_utils.send_password_reset_email
    """
    try:
        client = get_resend_client()
        return client.send_password_reset(user, token)
    except Exception as e:
        logger.error(f"Failed to send password reset email: {e}")
        return False


def send_welcome_email(user, verification_url: Optional[str] = None) -> bool:
    """
    Send welcome email via Resend.
    Drop-in replacement for email_utils.send_welcome_email
    """
    try:
        client = get_resend_client()
        return client.send_welcome_email(user, verification_url)
    except Exception as e:
        logger.error(f"Failed to send welcome email: {e}")
        return False


def send_magic_login_email(user, magic_url: str, *, submitted_email: str = None) -> bool:
    """Send a magic-link sign-in email. Never raises."""
    try:
        client = get_resend_client()
        return client.send_magic_login_link(user, magic_url, submitted_email=submitted_email)
    except Exception as e:
        logger.error(f"Failed to send magic-login email: {e}")
        return False


def send_verification_email(user, verification_url: str) -> bool:
    """
    Send a standalone verification email via Resend (used for resends after expiry).
    """
    try:
        client = get_resend_client()
        return client.send_verification_email(user, verification_url)
    except Exception as e:
        logger.error(f"Failed to send verification email: {e}")
        return False


def send_account_activation_email(user, activation_token: str) -> bool:
    """
    Send account activation email via Resend.
    Drop-in replacement for email_utils.send_account_activation_email
    """
    try:
        client = get_resend_client()
        return client.send_account_activation(user, activation_token)
    except Exception as e:
        logger.error(f"Failed to send account activation email: {e}")
        return False


def send_daily_question_welcome_email(subscriber) -> bool:
    """
    Send daily question welcome email via Resend.
    Drop-in replacement for email_utils.send_daily_question_welcome_email
    """
    try:
        client = get_resend_client()
        return client.send_daily_question_welcome(subscriber)
    except Exception as e:
        logger.error(f"Failed to send daily question welcome email: {e}")
        return False


def send_daily_question_email(subscriber, question) -> bool:
    """
    Send single daily question email via Resend.
    Drop-in replacement for email_utils.send_daily_question_email
    """
    try:
        client = get_resend_client()
        return client.send_daily_question(subscriber, question)
    except Exception as e:
        logger.error(f"Failed to send daily question email: {e}")
        return False


def send_discussion_notification_email(user, discussion, notification_type: str, additional_data: Optional[Dict] = None) -> bool:
    """
    Send discussion notification email via Resend.
    Drop-in replacement for email_utils.send_discussion_notification_email

    Args:
        user: User object to notify
        discussion: Discussion object
        notification_type: 'new_participant', 'new_response', 'discussion_update', or 'discussion_active'
        additional_data: Optional additional template data

    Returns:
        bool: Success status
    """
    try:
        client = get_resend_client()

        # Generate discussion URL
        base_url = client.base_url
        discussion_url = f"{base_url}/discussions/{discussion.id}/{discussion.slug}"

        is_host = user.id == discussion.creator_id

        # Prepare notification-specific content (align with in-app copy in email_utils).
        # All subject/message strings are resolved under the user's locale below.
        with force_locale(resolve_user_locale(user)):
            if notification_type == 'new_participant':
                subject = gettext("New participant in your discussion")
                message = gettext("Someone new has joined your discussion '%(title)s'", title=discussion.title)
            elif notification_type == 'new_response':
                if is_host:
                    subject = gettext("New activity in your discussion")
                    message = gettext("There's new activity in your discussion '%(title)s'", title=discussion.title)
                else:
                    subject = gettext("New activity in a discussion you follow")
                    message = gettext("There's new activity in a discussion you're following: '%(title)s'", title=discussion.title)
            elif notification_type == 'discussion_update':
                subject = gettext("Update: %(title)s", title=discussion.title)
                message = gettext("A new update was posted to '%(title)s'", title=discussion.title)
            else:
                subject = gettext("Activity in your discussion")
                message = gettext("There's been activity in your discussion '%(title)s'", title=discussion.title)

        # Render using the standard base email template
        settings_url = f"{base_url}/settings"
        html_content = _render_for_user(
            user,
            'emails/discussion_notification.html',
            username=user.username or 'there',
            subject=subject,
            message=message,
            discussion_title=discussion.title,
            discussion_url=discussion_url,
            notification_type=notification_type,
            settings_url=settings_url,
            base_url=base_url,
        )

        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': subject,
            'html': html_content,
            'headers': {
                'X-Entity-Ref-ID': _send_attempt_entity_ref(
                    f'discussion-{notification_type}',
                    getattr(discussion, 'id', 'na'),
                ),
            },
        }

        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Discussion notification email sent to {user.email}")
        else:
            logger.error(f"Failed to send discussion notification email to {user.email}")

        return success

    except Exception as e:
        logger.error(f"Failed to send discussion notification email: {e}")
        return False


def send_org_invitation_email(email: str, org_name: str, inviter_name: str, invite_url: str, role: str = 'editor', invitee_name: str = '') -> bool:
    """
    Send an organisation team invitation email for the paid Briefings product.

    This is used when a company-profile owner or admin invites a new member to
    their paid briefings workspace (Team / Enterprise plan). It is distinct from
    the Daily Brief subscription emails and from programme steward invites.

    Args:
        email:        Recipient email address.
        org_name:     Company/organisation name shown in the email.
        inviter_name: Display name of the person who sent the invite.
        invite_url:   Full URL the recipient clicks to accept (contains the token).
        role:         Role being granted – 'admin', 'editor', or 'viewer'.
        invitee_name: Optional first name for a personalised greeting.

    Returns:
        bool: True if the email was sent successfully, False otherwise.
    """
    try:
        client = get_resend_client()
        expiry_days = int(os.environ.get('PARTNER_INVITE_EXPIRY_DAYS', '7'))
        # Invitee may not have an account yet; best-effort locale by looking up
        # any existing User with this email, else fall back to English.
        invitee_user = None
        try:
            from app.models import User
            invitee_user = User.query.filter_by(email=email).first()
        except Exception:
            invitee_user = None
        html = _render_for_user(
            invitee_user,
            'emails/org_member_invite.html',
            org_name=org_name,
            inviter_name=inviter_name,
            invite_url=invite_url,
            role=role.capitalize(),
            invitee_name=invitee_name,
            expiry_days=expiry_days,
            base_url=client.base_url,
        )
        email_data = {
            'from': client.from_email,
            'to': [email],
            'subject': _subject_for_user(invitee_user, "You've been invited to join %(org)s on Society Speaks", org=org_name),
            'html': html,
            'headers': {
                'X-Entity-Ref-ID': _token_entity_ref(
                    'org-invite',
                    org_name,
                    _url_token_segment(invite_url) or invite_url,
                ),
            },
        }
        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Org invitation email sent to {email} for org '{org_name}'")
        else:
            logger.error(f"Failed to send org invitation email to {email}")
        return success
    except Exception as e:
        logger.error(f"Failed to send org invitation email to {email}: {e}")
        return False


def _send_user_transactional_email(
    user,
    template: str,
    subject: str,
    context: Dict[str, Any],
    client=None,
) -> bool:
    """Render and send a transactional email to a single user via Resend.

    Handles client lookup, template rendering, sending, and logging.
    'context' is merged with username and base_url automatically.
    """
    recipient = getattr(user, 'email', None)
    if not recipient:
        logger.error(f"Failed to send '{subject}': user has no email")
        return False

    from app.lib.user_display import friendly_display_name

    greeting_name = context.pop('username', None) or friendly_display_name(user)
    try:
        client = client or get_resend_client()
        html = _render_for_user(
            user,
            template,
            username=greeting_name,
            base_url=client.base_url,
            **context,
        )
        # `subject` is passed in already-translated by the caller (or as English
        # fallback). If the caller passed a raw English string, translate it here
        # under the user's locale so subjects localize even when callers haven't
        # been updated.
        localized_subject = _subject_for_user(user, subject) if isinstance(subject, str) else subject
        email_data = {
            'from': client.from_email,
            'to': [recipient],
            'subject': localized_subject,
            'html': html,
            'headers': {
                'X-Entity-Ref-ID': _send_attempt_entity_ref(
                    'user-tx', getattr(user, 'id', 'na')
                ),
            },
        }
        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Sent '{subject}' to {recipient}")
        else:
            logger.error(f"Failed to send '{subject}' to {recipient}")
        return success
    except Exception as e:
        logger.error(f"Failed to send '{subject}' to {recipient}: {e}")
        return False


def send_briefing_winback_email(
    user,
    resume_url: str,
) -> bool:
    """Day-45 winback for self-serve trials that auto-paused without converting.

    Sent once, ~15 days after the pause. Soft tone — emphasises data is
    preserved and resuming is one click. Idempotency enforced upstream
    via Redis SETNX on subscription id with a long (120-day) TTL.

    Args:
        user:        Recipient.
        resume_url:  Absolute URL of /billing/pending-checkout?plan=starter.

    Returns:
        True if the message was accepted for delivery.
    """
    return _send_user_transactional_email(
        user,
        'emails/briefing_winback.html',
        "Still here when you're ready",
        {'resume_url': resume_url},
    )


def send_briefing_welcome_from_william_email(
    user,
    dashboard_url: str,
) -> bool:
    """One-shot "from William" welcome note for self-serve trial signups.

    Sent once, immediately after :func:`start_self_serve_trial` returns a
    freshly-created subscription. Deliberately short and human-toned — the
    "feature grid" emails fire later in the lifecycle (trial mid, payment
    prompt). Idempotency is enforced upstream via a Redis SETNX on the
    user id.

    Args:
        user:           Recipient.
        dashboard_url:  Absolute URL to the user's briefing detail page.

    Returns:
        True if the message was accepted for delivery.
    """
    return _send_user_transactional_email(
        user,
        'emails/briefing_welcome_william.html',
        "A quick note about Personal Briefs",
        {'dashboard_url': dashboard_url},
    )


def send_briefing_trial_payment_prompt_email(
    user,
    checkout_url: str,
    days_remaining: int,
) -> bool:
    """Day-25 conversion prompt for self-serve trial users.

    Sent ~5 days before trial end if the user has no payment method on
    file. Pitches "keep your briefs coming" with a single CTA to the
    Stripe pending_checkout entry point.

    Idempotency is enforced upstream via a Redis SETNX on the subscription
    id — this function never checks for duplicates.

    Args:
        user:            Recipient (must have ``email`` and ``username``).
        checkout_url:    Absolute URL of /billing/pending-checkout?plan=starter.
        days_remaining:  Days left in the trial (typically 5 when this fires).

    Returns:
        True if the message was accepted for delivery.
    """
    return _send_user_transactional_email(
        user,
        'emails/briefing_trial_payment.html',
        # Subject is a static msgid (translator-friendly); day count lives in
        # the body. F-string subjects don't extract into messages.pot and the
        # variant-per-day pattern means no translation ever matches at runtime.
        "Keep your morning brief — your trial is ending soon",
        {
            'checkout_url': checkout_url,
            'days_remaining': days_remaining,
        },
    )


def send_briefing_paused_email(
    user,
    resume_url: str,
) -> bool:
    """One-shot "your briefs are paused" email after self-serve trial expiry.

    Soft framing — emphasises that data is preserved and resuming is one
    click. No charges, no scary warnings.

    Args:
        user:        Recipient.
        resume_url:  Absolute URL of /billing/pending-checkout?plan=starter
                     so a single click takes them to Stripe Checkout.

    Returns:
        True if the message was accepted for delivery.
    """
    return _send_user_transactional_email(
        user,
        'emails/briefing_paused.html',
        "Your briefs are paused — pick up where you left off any time",
        {'resume_url': resume_url},
    )


def send_briefing_activation_nudge_email(
    user,
    start_url: str,
) -> bool:
    """
    Activation nudge sent ~48h after subscription if the user still has zero
    briefings. One-shot, fired by the scheduler; idempotency is enforced
    upstream via a Redis key on the subscription id.

    Args:
        user:      Recipient (must have ``email`` and ``username``).
        start_url: Absolute URL of the template-selection / first-brief entry
                   point (either /briefings/start or /briefings/ depending on
                   the SELF_SERVE_TRIAL_ENABLED flag).

    Returns:
        True if the message was accepted for delivery.
    """
    return _send_user_transactional_email(
        user,
        'emails/briefing_activation_nudge.html',
        "Your first brief is two minutes away",
        {'start_url': start_url},
    )


def send_trial_ending_email(
    user,
    days_remaining: int = 3,
    *,
    manage_billing_url: Optional[str] = None,
    pricing_url: Optional[str] = None,
    upgrade_url: Optional[str] = None,
) -> bool:
    """
    Notify a paid-briefings subscriber that their free trial is ending soon.

    Triggered by the Stripe ``customer.subscription.trial_will_end`` webhook (fires
    three days before trial end). Stripe recommends pointing customers at billing
    where they can add a payment method before the trial converts.

    Args:
        user: Recipient (must have ``email`` and ``username``).
        days_remaining: Days left in the trial (typically ``3`` from Stripe).
        manage_billing_url: Absolute URL to our billing portal entrypoint (login
            required). Defaults to ``{base}/billing/portal``.
        pricing_url: Absolute URL to plans / upgrade marketing (e.g. landing ``#pricing``).
        upgrade_url: Deprecated; used as ``pricing_url`` when ``pricing_url`` is omitted.

    Returns:
        True if the message was accepted for delivery.
    """
    client = None
    try:
        client = get_resend_client()
        base = client.base_url.rstrip('/')
    except Exception:
        base = ''

    if not manage_billing_url:
        manage_billing_url = f'{base}/billing/card-update' if base else '/billing/card-update'

    resolved_pricing = pricing_url or upgrade_url
    if not resolved_pricing:
        resolved_pricing = f'{base}/briefings/landing#pricing' if base else '/briefings/landing#pricing'

    template_ctx = {
        'days_remaining': days_remaining,
        'manage_billing_url': manage_billing_url,
        'pricing_url': resolved_pricing,
    }

    return _send_user_transactional_email(
        user,
        'emails/trial_ending.html',
        f"Your free trial ends in {days_remaining} day{'s' if days_remaining != 1 else ''} — keep your briefings going",
        template_ctx,
        client=client,
    )


def send_subscription_cancelled_email(user, resubscribe_url: Optional[str] = None, briefing_count: int = 0) -> bool:
    """
    Notify a user that their subscription has been cancelled and their briefings paused.

    Triggered by the Stripe ``customer.subscription.deleted`` webhook.

    Args:
        user:             User object (must have .email and .username).
        resubscribe_url:  Full URL to the plans/pricing page (defaults to landing#pricing).
        briefing_count:   Number of briefings that were paused.

    Returns:
        bool: True if sent successfully.
    """
    client = None
    try:
        client = get_resend_client()
        base = client.base_url.rstrip('/')
    except Exception:
        base = ''

    if not resubscribe_url:
        resubscribe_url = f'{base}/briefings/landing#pricing' if base else '/briefings/landing#pricing'

    return _send_user_transactional_email(
        user,
        'emails/subscription_cancelled.html',
        "We've paused your briefings — come back any time",
        {'resubscribe_url': resubscribe_url, 'briefing_count': briefing_count},
        client=client,
    )


def send_trial_mid_email(
    user,
    days_remaining: int,
    *,
    manage_billing_url: Optional[str] = None,
    briefings_url: Optional[str] = None,
) -> bool:
    """
    Mid-trial engagement email sent at approximately day 7 of the 30-day trial.

    Reminds the user of what their subscription includes, shows progress, and
    encourages them to add a payment method while emphasising no charge until
    day 30.

    Args:
        user:               Recipient (must have ``email`` and ``username``).
        days_remaining:     Days remaining in the trial (typically ~23 at day 7).
        manage_billing_url: Absolute URL to billing portal / card-update entrypoint.
        briefings_url:      Absolute URL to the user's briefings list.

    Returns:
        True if the message was accepted for delivery.
    """
    client = None
    try:
        client = get_resend_client()
        base = client.base_url.rstrip('/')
    except Exception:
        base = ''

    if not manage_billing_url:
        manage_billing_url = f'{base}/billing/card-update' if base else '/billing/card-update'
    if not briefings_url:
        briefings_url = f'{base}/briefings' if base else '/briefings'

    return _send_user_transactional_email(
        user,
        'emails/trial_mid.html',
        f"You're one week into your free trial — {days_remaining} days left",
        {
            'days_remaining': days_remaining,
            'manage_billing_url': manage_billing_url,
            'briefings_url': briefings_url,
        },
        client=client,
    )


def send_profile_completion_reminder_email(user, missing_fields: list, profile_url: str) -> bool:
    """
    Send profile completion reminder email via Resend.
    Drop-in replacement for email_utils.send_profile_completion_reminder_email
    
    Args:
        user: User object
        missing_fields: List of incomplete profile fields
        profile_url: URL to edit profile
        
    Returns:
        bool: Success status
    """
    try:
        client = get_resend_client()
        
        html = _render_for_user(
            user,
            'emails/profile_completion_reminder.html',
            username=user.username or 'there',
            missing_fields=missing_fields,
            profile_url=profile_url,
            base_url=client.base_url
        )

        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': _subject_for_user(user, 'Complete Your Society Speaks Profile'),
            'html': html
        }
        
        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Profile completion reminder sent to {user.email}")
            # Record analytics event
            from app.lib.email_analytics import EmailAnalytics
            EmailAnalytics.record_send(
                email=user.email,
                category=EmailAnalytics.CATEGORY_AUTH,
                subject='Complete Your Society Speaks Profile',
                user_id=user.id
            )
        else:
            logger.error(f"Failed to send profile completion reminder to {user.email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send profile completion reminder: {e}")
        return False


def send_weekly_discussion_digest(user, digest_data: dict) -> bool:
    """
    Send weekly discussion digest email via Resend.
    
    Args:
        user: User object
        digest_data: Dict containing:
            - discussions_with_activity: List of dicts with discussion activity
            - trending_topics: List of trending discussions
            - stats: Dict with user's weekly stats
            
    Returns:
        bool: True if sent successfully, False otherwise
    """
    try:
        client = get_resend_client()
        
        # Build URLs
        dashboard_url = f"{client.base_url}/dashboard"
        settings_url = f"{client.base_url}/settings"
        
        # Render template
        html = _render_for_user(
            user,
            'emails/weekly_digest.html',
            username=user.username or 'there',
            discussions_with_activity=digest_data.get('discussions_with_activity', []),
            trending_topics=digest_data.get('trending_topics', []),
            stats=digest_data.get('stats', {
                'discussions_created': 0,
                'votes_cast': 0,
                'responses_written': 0
            }),
            dashboard_url=dashboard_url,
            settings_url=settings_url,
            base_url=client.base_url
        )

        email_data = {
            'from': client.from_email,
            'to': [user.email],
            'subject': _subject_for_user(user, 'Your Weekly Discussion Digest - Society Speaks'),
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{settings_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Week + user + fingerprint of discussion ids in this payload.
                'X-Entity-Ref-ID': _weekly_digest_ref(
                    'weekly-discussion-digest',
                    user.id,
                    *(
                        d.get('id') or d.get('discussion_id') or ''
                        for d in digest_data.get('discussions_with_activity', [])
                    ),
                ),
            }
        }
        
        success = client._send_with_retry(email_data, use_rate_limit=False)
        
        if success:
            logger.info(f"Weekly digest sent to {user.email}")
            # Record analytics event
            from app.lib.email_analytics import EmailAnalytics
            EmailAnalytics.record_send(
                email=user.email,
                category=EmailAnalytics.CATEGORY_AUTH,  # Could create CATEGORY_DIGEST
                subject='Your Weekly Discussion Digest',
                user_id=user.id
            )
        else:
            logger.error(f"Failed to send weekly digest to {user.email}")
        
        return success
        
    except Exception as e:
        logger.error(f"Failed to send weekly digest: {e}")
        return False


def send_daily_question_to_all_subscribers() -> int:
    """
    Send today's daily question to all active subscribers using batch API.
    Drop-in replacement for email_utils.send_daily_question_to_all_subscribers

    Returns:
        int: Number of emails successfully sent
    """
    from app.models import DailyQuestion, DailyQuestionSubscriber
    from app import db

    # Get today's question
    question = DailyQuestion.get_today()
    if not question:
        logger.info("No daily question to send - none published for today")
        return 0

    # Get all active subscribers with 'daily' frequency (filter for weekly digest feature)
    total_subscribers = DailyQuestionSubscriber.query.filter_by(
        is_active=True,
        email_frequency='daily'
    ).count()

    if total_subscribers == 0:
        logger.info("No active daily frequency subscribers to send daily question to")
        return 0

    logger.info(
        f"Starting daily question #{question.question_number} send to {total_subscribers} daily frequency subscribers "
        f"(using batch API for efficiency)"
    )

    start_time = time.time()
    
    try:
        client = get_resend_client()
    except Exception as e:
        logger.error(f"Failed to initialize Resend client: {e}")
        return 0

    # Process in chunks to manage memory
    CHUNK_SIZE = 500
    total_sent = 0
    total_failed = 0
    skipped_duplicates = 0
    offset = 0

    while True:
        # Get chunk of subscribers (filtered by daily frequency)
        subscribers = DailyQuestionSubscriber.query.filter_by(
            is_active=True,
            email_frequency='daily'
        ).order_by(DailyQuestionSubscriber.id)\
            .offset(offset)\
            .limit(CHUNK_SIZE)\
            .all()

        if not subscribers:
            break

        # Filter out subscribers who already received today's email (duplicate prevention)
        eligible_subscribers = []
        for subscriber in subscribers:
            if subscriber.can_receive_email():
                eligible_subscribers.append(subscriber)
            else:
                skipped_duplicates += 1
        
        if not eligible_subscribers:
            offset += CHUNK_SIZE
            continue

        # Refresh magic tokens and ensure stable unsubscribe tokens for this chunk
        for subscriber in eligible_subscribers:
            subscriber.generate_magic_token()
            subscriber.ensure_unsubscribe_token()
        
        try:
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to generate magic tokens: {e}")
            db.session.rollback()
            offset += CHUNK_SIZE
            continue

        # Send batch
        results = client.send_daily_question_batch(eligible_subscribers, question)
        total_sent += results['sent']
        total_failed += results['failed']

        if results['errors']:
            for error in results['errors'][:5]:  # Log first 5 errors
                logger.warning(f"Batch error: {error}")

        offset += CHUNK_SIZE

        # Progress log
        elapsed = time.time() - start_time
        rate = total_sent / elapsed if elapsed > 0 else 0
        logger.info(
            f"Progress: {total_sent} sent, {total_failed} failed "
            f"({rate:.1f} emails/sec)"
        )

    elapsed_total = time.time() - start_time
    final_rate = total_sent / elapsed_total if elapsed_total > 0 else 0

    logger.info(
        f"Daily question #{question.question_number} complete: "
        f"{total_sent} sent, {total_failed} failed, {skipped_duplicates} skipped (already sent) "
        f"of {total_subscribers} in {elapsed_total:.1f} seconds ({final_rate:.1f} emails/sec)"
    )

    return total_sent


def send_journey_reminder_email(
    subscription,
    programme,
    next_discussion,
    theme_checklist: list,
    completed_themes: int,
    total_themes: int,
    base_url: str = None,
) -> bool:
    """
    Send a progress-based journey reminder email.

    Args:
        subscription: JourneyReminderSubscription instance
        programme: Programme instance
        next_discussion: Discussion instance for the next incomplete theme
        theme_checklist: list of dicts with keys 'name' and 'is_complete'
        completed_themes: int — how many themes the user has finished
        total_themes: int — total themes in the journey
        base_url: override base URL (defaults to client.base_url)

    Returns:
        bool: True if sent successfully
    """
    try:
        client = get_resend_client()
        _base = base_url or client.base_url

        resume_token = subscription.generate_resume_token(expires_hours=72)
        unsub_token = subscription.ensure_unsubscribe_token()
        programme_url = f"{_base}/programmes/{programme.slug}"
        continue_url = (
            f"{programme_url}?jrt={resume_token}"
            if not subscription.user_id
            else f"{_base}/programmes/{programme.slug}"
        )
        unsubscribe_url = (
            f"{_base}/programmes/{programme.slug}/journey-reminder/unsubscribe"
            f"?token={unsub_token}"
        )

        pct = int((completed_themes / total_themes * 100)) if total_themes else 0
        next_theme_name = (
            getattr(next_discussion, 'programme_theme', None) or next_discussion.title
        )
        # Count active, approved statements for this discussion rather than using a
        # non-existent attribute. Falls back to 7 (the seed minimum) if the query fails.
        try:
            from app.models import Statement
            next_statement_count = Statement.query.filter_by(
                discussion_id=next_discussion.id,
                is_deleted=False,
            ).filter(Statement.mod_status >= 0).count() or 7
        except Exception:
            next_statement_count = 7

        # Resolve the journey subscriber's user for locale (anonymous → 'en')
        _journey_user = subscription.user if subscription.user_id else None
        html = _render_for_user(
            _journey_user,
            'emails/journey_reminder.html',
            username=subscription.email.split('@')[0] if not subscription.user_id else (
                subscription.user.username if subscription.user else subscription.email.split('@')[0]
            ),
            programme_name=programme.name,
            programme_url=programme_url,
            continue_url=continue_url,
            unsubscribe_url=unsubscribe_url,
            completed_themes=completed_themes,
            total_themes=total_themes,
            pct=pct,
            next_theme_name=next_theme_name,
            next_statement_count=next_statement_count,
            theme_checklist=theme_checklist,
            is_anonymous=not subscription.user_id,
            theme_minutes_display_hint=GUIDED_JOURNEY_DISPLAY_MINUTES_PER_THEME,
        )

        email_data = {
            'from': client.from_email,
            'to': [subscription.email],
            'subject': _subject_for_user(_journey_user, 'Continue your journey: %(theme)s — Society Speaks', theme=next_theme_name),
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Idempotency-Key. reminder_count increments only after a
                # committed send, so a retry of the same reminder reuses the key
                # while the next scheduled one gets a fresh one.
                'X-Entity-Ref-ID': scoped_entity_ref(
                    'journey-reminder',
                    subscription.id,
                    (subscription.reminder_count or 0) + 1,
                ),
            },
        }

        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Journey reminder sent to {subscription.email} for {programme.slug}")
        else:
            logger.error(f"Failed to send journey reminder to {subscription.email}")
        return success

    except Exception as e:
        logger.error(f"Failed to send journey reminder email: {e}", exc_info=True)
        return False


def send_game_reminder_email(
    subscription,
    *,
    scenario_meta: dict,
    streak: dict = None,
    base_url: str = None,
) -> bool:
    """Send a daily "today's scenario is live / keep your streak" nudge.

    Args:
        subscription: GameReminderSubscription instance
        scenario_meta: dict from daily_service.daily_meta (title/subtitle/etc.)
        streak: dict from compute_daily_streak (uses 'current')
        base_url: override base URL (defaults to client.base_url)
    """
    try:
        client = get_resend_client()
        _base = base_url or client.base_url

        token = subscription.ensure_unsubscribe_token()
        play_url = f"{_base}/play"
        unsubscribe_url = f"{_base}/play/reminders/unsubscribe?token={token}"

        streak = streak or {}
        current_streak = int(streak.get('current') or 0)
        has_streak = current_streak >= 2

        _user = subscription.user if subscription.user_id else None
        if _user and getattr(_user, 'username', None):
            username = _user.username
        else:
            username = subscription.email.split('@')[0]

        scenario_title = scenario_meta.get('title') or 'Society Speaks'

        html = _render_for_user(
            _user,
            'emails/game_reminder.html',
            username=username,
            play_url=play_url,
            unsubscribe_url=unsubscribe_url,
            scenario_title=scenario_title,
            scenario_subtitle=scenario_meta.get('subtitle') or '',
            scenario_category=scenario_meta.get('category') or '',
            scenario_teaser=scenario_meta.get('teaser') or '',
            total_turns=scenario_meta.get('total_turns') or 5,
            current_streak=current_streak,
            has_streak=has_streak,
        )

        if has_streak:
            subject = _subject_for_user(
                _user,
                "Today's scenario is live — keep your %(n)d-day streak",
                n=current_streak,
            )
        else:
            subject = _subject_for_user(
                _user,
                "Today's scenario is live: %(title)s",
                title=scenario_title,
            )

        email_data = {
            'from': client.from_email,
            'to': [subscription.email],
            'subject': subject,
            'html': html,
            'headers': {
                'List-Unsubscribe': f'<{unsubscribe_url}>',
                'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                # Idempotency-Key. reminder_count increments only after a
                # committed send, so a retry of the same reminder reuses the key
                # while the next scheduled one gets a fresh one.
                'X-Entity-Ref-ID': scoped_entity_ref(
                    'game-reminder',
                    subscription.id,
                    (subscription.reminder_count or 0) + 1,
                ),
            },
        }

        success = client._send_with_retry(email_data, use_rate_limit=False)
        if success:
            logger.info(f"Game reminder sent to {subscription.email}")
        else:
            logger.error(f"Failed to send game reminder to {subscription.email}")
        return success

    except Exception as e:
        logger.error(f"Failed to send game reminder email: {e}", exc_info=True)
        return False
