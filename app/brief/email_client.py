"""
Resend Email Client for Daily Brief

Handles email delivery via Resend API with timezone support.
"""

import os
import re
import secrets
import threading
import logging
import pytz
from contextlib import nullcontext
from datetime import datetime, date, timedelta
from app.lib.time import utcnow_naive
from email.utils import parseaddr
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from flask import render_template, current_app
from app.models import DailyBrief, DailyBriefSubscriber, BriefItem, db
from app.brief.sections import SECTIONS, TOPIC_DISPLAY_LABELS, TOPIC_DISPLAY_COLORS
from app.email_utils import RateLimiter, extract_clean_email
from app.resend_client import (
    resend_post_with_retry,
    _email_sending_allowed_for_environment,
)
from app.lib.email_idempotency import (
    ensure_email_idempotency,
    scoped_entity_ref,
    send_attempt_entity_ref,
)
from app.briefing.link_tracker import wrap_links as _wrap_links, sign_url as _sign_url
from app.lib.unsubscribe_tokens import build_brief_unsubscribe_url
from app.storage_utils import get_base_url

try:
    import sentry_sdk as _sentry_sdk
except ImportError:
    _sentry_sdk = None

logger = logging.getLogger(__name__)


def build_brief_magic_link_url(
    base_url: str,
    token: str,
    brief: Optional[DailyBrief] = None,
) -> str:
    """Subscriber magic link that opens *this* edition, not whatever is latest.

    Welcome emails omit *brief* so they still land on the current edition.
    """
    url = f"{(base_url or '').rstrip('/')}/brief/m/{token}"
    if not brief or not getattr(brief, 'date', None):
        return url
    url = f"{url}?d={brief.date.isoformat()}"
    if getattr(brief, 'brief_type', 'daily') == 'weekly':
        url = f"{url}&type=weekly"
    return url


def public_brief_url(base_url: str, brief: Optional[DailyBrief] = None) -> str:
    """Canonical public permalink for an edition — no magic token, no 'today' alias."""
    root = (base_url or '').rstrip('/')
    if not brief or not getattr(brief, 'date', None):
        return f'{root}/brief'
    date_str = brief.date.isoformat()
    if getattr(brief, 'brief_type', 'daily') == 'weekly':
        return f'{root}/brief/weekly/{date_str}'
    return f'{root}/brief/{date_str}'


def permalink_from_magic_link_url(url: str) -> Optional[str]:
    """Derive the public dated permalink from a pinned ``/brief/m/…?d=`` URL."""
    if not url or url == '#':
        return None
    try:
        parsed = urlparse(url)
    except Exception:
        return None
    if '/brief/m/' not in (parsed.path or ''):
        return None
    qs = dict(parse_qsl(parsed.query, keep_blank_values=True))
    date_str = (qs.get('d') or qs.get('date') or '').strip()
    if not date_str:
        return None
    try:
        datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None
    origin = (
        f'{parsed.scheme}://{parsed.netloc}'
        if parsed.scheme and parsed.netloc
        else ''
    )
    path = (
        f'/brief/weekly/{date_str}'
        if qs.get('type') == 'weekly'
        else f'/brief/{date_str}'
    )
    return f'{origin}{path}'


def pin_magic_link_to_edition(target_url: str, brief: Optional[DailyBrief]) -> str:
    """Attach this edition's date to an unpinned ``/brief/m/`` URL.

    Already-sent emails wrap ``/brief/m/<token>`` through click tracking with
    no date. Pinning here is what makes those old inbox links open the
    edition they were sent for, instead of today's brief.
    """
    if not target_url or not brief or not getattr(brief, 'date', None):
        return target_url
    try:
        parsed = urlparse(target_url)
    except Exception:
        return target_url
    if '/brief/m/' not in (parsed.path or ''):
        return target_url
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    keys = {key for key, _value in pairs}
    if 'd' in keys or 'date' in keys:
        return target_url
    pairs.append(('d', brief.date.isoformat()))
    if getattr(brief, 'brief_type', 'daily') == 'weekly':
        pairs.append(('type', 'weekly'))
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        parsed.path,
        parsed.params,
        urlencode(pairs),
        parsed.fragment,
    ))


# Failure classification ------------------------------------------------------
# resend_post_with_retry returns errors like "API error: 400 - <body>" (client
# already retried 408/429/5xx including Cloudflare 52x internally). We map
# those to a send-handling policy.
_RESEND_STATUS_RE = re.compile(r'API error:\s*(\d{3})')

# Resend's definitive "this address is invalid" signal — suppress immediately.
_INVALID_RECIPIENT_CODES = frozenset({422})
# Per-recipient permanent failures where retrying identical content won't help
# but the cause is ambiguous (a 400 for one recipient while others succeed is
# recipient-specific). Counted toward eventual suppression rather than instant.
# Deliberately excludes 401/403 (account/global auth) so an API-key problem can
# never suppress individual subscribers.
_PERMANENT_RECIPIENT_CODES = frozenset({400})
# Brief sends pass these to resend_post_with_retry so per-recipient 400/422
# log at WARNING in the HTTP client; transactional flows keep ERROR.
# Retryable 5xx/408/429 use warn_on_retryable=True (catch-up retries the claim).
_BRIEF_RESEND_WARN_STATUSES = frozenset({400, 422})
# Isolated Cloudflare/Resend blips must not page. A batch of this many
# pageable failures in one run is treated as an outage and logs ERROR.
_PAGEABLE_BATCH_ERROR_THRESHOLD = 5
_RESEND_ERROR_LOG_MAX_LEN = 240
_RE_HTML_TAGS = re.compile(r'<[^>]+>')


def truncate_resend_error(error: Optional[str], max_len: int = _RESEND_ERROR_LOG_MAX_LEN) -> str:
    """Normalize a Resend error string for structured logs (strip HTML, cap length)."""
    if not error:
        return ''
    text = _RE_HTML_TAGS.sub(' ', str(error))
    text = ' '.join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + '...'


def build_send_failure_record(
    *,
    subscriber_id: int,
    email: str,
    brief_id: Optional[int],
    resend_error: Optional[str],
    send_failure_count: int = 0,
    classification: Optional[str] = None,
) -> Dict[str, Any]:
    """Structured failure payload for logs, batch results, and admin triage."""
    resolved_classification = classification or classify_send_failure(resend_error)
    truncated = truncate_resend_error(resend_error)
    threshold = DailyBriefSubscriber.SEND_FAILURE_SUPPRESS_THRESHOLD
    return {
        'subscriber_id': subscriber_id,
        'email': email,
        'brief_id': brief_id,
        'classification': resolved_classification,
        'resend_error': truncated,
        'send_failure_count': send_failure_count,
        'suppress_threshold': threshold,
        'pageable': resolved_classification == 'transient',
    }


def format_send_failure_message(record: Dict[str, Any]) -> str:
    """Single canonical log line for a per-recipient brief send failure."""
    return (
        f"Brief send failed [{record['classification']}]: "
        f"subscriber_id={record['subscriber_id']} "
        f"email={record['email']} "
        f"send_failures={record['send_failure_count']}/{record['suppress_threshold']} "
        f"brief_id={record['brief_id']} "
        f"resend={record['resend_error']!r}"
    )


def log_send_failure(record: Dict[str, Any]) -> None:
    """Emit one structured log for a send failure at the correct severity.

    Pageable (transient) failures already exhausted HTTP retries and will be
    picked up by catch-up — WARNING, not ERROR, so one Cloudflare 520 does
    not page. Permanent/invalid stay WARNING as well (one bad address must
    not page). Extra omits the raw email so Sentry does not store PII.
    """
    msg = format_send_failure_message(record)
    extra = {k: v for k, v in record.items() if k != 'email'}
    logger.warning(msg, extra=extra)


def _attach_brief_send_metadata(results: dict, brief, *, cadence: str) -> dict:
    """Stamp scheduler batch results with brief edition metadata for analytics."""
    if not results or not brief:
        return results
    meta = {
        'brief_id': brief.id,
        'brief_date': brief.date.isoformat() if brief.date else None,
        'brief_type': getattr(brief, 'brief_type', None) or cadence,
        'cadence': cadence,
    }
    try:
        from app.models import DailyQuestion

        dq = DailyQuestion.query.filter_by(question_date=brief.date).first()
        if dq:
            meta['daily_question_id'] = dq.id
    except Exception:
        pass
    results['_send_meta'] = meta
    return results


def _capture_daily_brief_sent_batch(results: dict, *, cadence: str) -> None:
    """Emit one PostHog system event per scheduler batch with actual send activity."""
    sent = int(results.get('sent') or 0)
    failed = int(results.get('failed') or 0)
    if sent + failed <= 0:
        return
    meta = results.get('_send_meta') or {}
    try:
        from app.lib.posthog_utils import safe_system_capture

        safe_system_capture(
            'daily_brief_sent',
            properties={
                'cadence': cadence,
                'sent': sent,
                'failed': failed,
                'brief_id': meta.get('brief_id'),
                'brief_date': meta.get('brief_date'),
                'brief_type': meta.get('brief_type'),
                'daily_question_id': meta.get('daily_question_id'),
            },
            insert_id=f'daily_brief_sent:{cadence}:{meta.get("brief_id") or meta.get("brief_date") or "batch"}',
        )
    except Exception as exc:
        logger.warning('PostHog daily_brief_sent capture failed: %s', exc)


def log_brief_batch_results(results: Optional[dict], *, cadence: str = 'daily') -> None:
    """Log batch send summary for scheduler jobs.

    Per-recipient failures are logged once inside ``send_to_subscribers``; this
    helper only emits the batch summary so scheduler jobs do not duplicate them.
    """
    if not results:
        return
    label = 'Daily' if cadence == 'daily' else 'Weekly'
    sent = int(results.get('sent') or 0)
    failed = int(results.get('failed') or 0)
    logger.info('%s brief batch complete: %d sent, %d failed', label, sent, failed)
    if failed:
        pageable = sum(1 for f in (results.get('failures') or []) if f.get('pageable'))
        permanent = failed - pageable
        if pageable:
            summary = (
                '%s brief batch had %d pageable failure(s) '
                '(infra/transient — claim released for retry)'
            )
            if pageable >= _PAGEABLE_BATCH_ERROR_THRESHOLD:
                logger.error(summary, label, pageable)
            else:
                logger.warning(summary, label, pageable)
        if permanent:
            logger.warning(
                '%s brief batch had %d per-recipient failure(s) (logged individually above)',
                label,
                permanent,
            )
    _capture_daily_brief_sent_batch(results, cadence=cadence)


def classify_send_failure(error: Optional[str]) -> str:
    """Classify a Resend send-error string into a handling policy.

    Returns one of:
        'invalid_recipient' — Resend rejected the address (422); suppress now.
        'permanent'         — per-recipient permanent failure (e.g. 400); stop
                              retrying this edition and count toward suppression.
        'transient'         — rate-limit, 5xx, auth/global, network, or unknown;
                              safe (and worth) retrying.
    """
    if not error:
        return 'transient'
    match = _RESEND_STATUS_RE.search(error)
    if not match:
        return 'transient'
    code = int(match.group(1))
    if code in _INVALID_RECIPIENT_CODES:
        return 'invalid_recipient'
    if code in _PERMANENT_RECIPIENT_CODES:
        return 'permanent'
    return 'transient'


_SYSTEM_FONT = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
    "'Helvetica Neue',Arial,sans-serif"
)
_SERIF_FONT = "Georgia,'Times New Roman',serif"

_RE_WHITESPACE_BETWEEN_TAGS = re.compile(r'>\s{2,}<')
_RE_HTML_COMMENT = re.compile(
    r'<!--(?!\[if )(?!<!\[endif\])(?!/?email-trim:)(?! Footer -->).*?-->',
    re.DOTALL,
)
# Apple Mail's inbox-snippet generator pulls text out of <style> blocks,
# including prose inside /* ... */ comments, ignoring the hidden preheader.
# Strip CSS comments so they can never leak into the preview.
_RE_CSS_COMMENT = re.compile(r'/\*.*?\*/', re.DOTALL)
_RE_BLANK_LINES = re.compile(r'\n\s*\n')
_RE_STYLE_ATTR = re.compile(r'(style=")(.*?)(")', re.DOTALL)
_RE_TAG_LINE_INDENT = re.compile(r'^[ \t]+(</?\w)', re.MULTILINE)

# Gmail clips HTML around 102 KB. The fitter targets a lower figure because
# click-tracking (wrap_links) rewrites every href AFTER the email is rendered,
# expanding the HTML by a few KB that must still land under the hard limit.
GMAIL_CLIP_LIMIT_BYTES = 102 * 1024
GMAIL_CLIP_TARGET_BYTES = 96 * 1024

# Overflow strategy, in order. The headline index is deliberately NOT here: it is
# the brief's table of contents (every story, cheap in bytes) and is never trimmed,
# so a reader always sees the full menu even when story bodies are collapsed to the
# web. We shed low-value chrome first, then the editorial lens-check, and only then
# collapse the lowest-priority story bodies from the bottom up (those stories remain
# in the protected index with a "read the full brief on the web" pointer).
_EMAIL_TRIM_ORDER = (
    'thank-you',
    'personal-briefs-cta',
    'tradeoffs',
    'lens-check',
)

# Every text element also gets the sans-serif stack from an element-level rule in
# the email's <head> <style> (which Outlook and Gmail both honour), so these
# redundant inline copies can be stripped to save ~20 KB per brief. Georgia
# headline cells keep their inline font (higher specificity), so only the
# sans-serif stack is targeted here.
_RE_INLINE_SANS_FONT = re.compile(
    r"font-family:\s*"
    + re.escape(_SYSTEM_FONT)
    + r"\s*;?\s*",
    re.IGNORECASE,
)
_RE_INLINE_SANS_FONT_LONG = re.compile(
    r"font-family:\s*-apple-system[^;\"]{10,320};?\s*",
    re.IGNORECASE,
)


# Page background colour of the email's <body> (see daily_brief.html). Used only
# to recognise the <body> style attribute so its font-family is kept as a fallback.
# If it ever drifts from the template the <head> <style> rule still covers <body>.
_BODY_BG_SIGNATURE = '#f1f5f9'


def _compact_style(match: re.Match) -> str:
    prefix, decls, suffix = match.group(1), match.group(2), match.group(3)
    decls = ' '.join(decls.split())
    # Strip redundant inline sans-serif copies from THIS style attribute only.
    # Scoping the strip to style="..." attributes (rather than the whole document)
    # leaves the <head> <style> font rule intact, so every client still resolves
    # the correct font. Georgia headline cells are untouched (their stack does not
    # match the sans pattern). The <body> declaration is kept verbatim as a
    # belt-and-suspenders fallback for clients that ignore <style> but do inherit
    # font-family from <body> (identified by the page background colour).
    if _BODY_BG_SIGNATURE not in decls:
        decls = _RE_INLINE_SANS_FONT.sub('', decls)
        decls = _RE_INLINE_SANS_FONT_LONG.sub('', decls)
        decls = decls.strip().rstrip(';').strip()
    return prefix + decls + suffix


def _email_html_byte_size(html: str) -> int:
    return len(html.encode('utf-8'))


_RE_STORY_PERSPECTIVES = re.compile(
    r'<!--email-trim:story-perspectives-->.*?<!--/email-trim:story-perspectives-->',
    re.DOTALL,
)


def _remove_last_story_perspectives(html: str) -> tuple[str, bool]:
    """Drop the perspectives block from the lowest-priority (last) story first.

    Only targets blocks that actually contain a perspectives row. Quick-depth
    stories still emit the marker pair with nothing between them; skipping those
    keeps the removed-count honest and avoids pointless passes over the document.
    """
    last = None
    for match in _RE_STORY_PERSPECTIVES.finditer(html):
        if '<tr' in match.group(0):
            last = match
    if last is None:
        return html, False
    return html[:last.start()] + html[last.end():], True


def _strip_perspectives_from_tail_stories(html: str, limit: int) -> tuple[str, int]:
    """Shed left/centre/right framing from tail stories before collapsing whole cards."""
    removed = 0
    while _email_html_byte_size(html) > limit:
        next_html, changed = _remove_last_story_perspectives(html)
        if not changed:
            break
        html = next_html
        removed += 1
    return html, removed


def _remove_email_trim_section(html: str, section_id: str) -> str:
    pattern = re.compile(
        rf'<!--email-trim:{re.escape(section_id)}-->.*?<!--/email-trim:{re.escape(section_id)}-->',
        re.DOTALL,
    )
    return pattern.sub('', html, count=1)


_STORY_ROW_START = re.compile(r'<tr id="item-\d+">')


def _split_story_rows(html: str) -> tuple[str, list[str], str]:
    matches = list(_STORY_ROW_START.finditer(html))
    if not matches:
        return html, [], ''
    prefix = html[:matches[0].start()]
    suffix_start = len(html)
    for sentinel in (
        '<!--email-trim:lens-check-->',
        '<!--email-trim:tradeoffs-->',
        '<!--email-trim:thank-you-->',
        '<!-- Footer -->',
    ):
        idx = html.find(sentinel, matches[-1].start())
        if idx > matches[-1].start():
            suffix_start = min(suffix_start, idx)
    rows = []
    for i, match in enumerate(matches):
        start = match.start()
        if i + 1 < len(matches):
            end = matches[i + 1].start()
        elif suffix_start > start:
            end = suffix_start
        else:
            end = len(html)
        rows.append(html[start:end])
    suffix = html[suffix_start:]
    return prefix, rows, suffix


def _extract_magic_link_url(html: str) -> str | None:
    match = re.search(r'href="([^"]+/brief/m/[^"]+)"', html)
    return match.group(1) if match else None


def _web_url_for_trimmed_stories(html: str) -> str:
    """Public dated permalink when the magic link is pinned; else the magic URL."""
    magic_url = _extract_magic_link_url(html) or ''
    return permalink_from_magic_link_url(magic_url) or magic_url or '#'


def _append_read_more_notice(html: str, removed_count: int) -> str:
    if removed_count <= 0:
        return html
    web_url = _web_url_for_trimmed_stories(html)
    story_word = 'story' if removed_count == 1 else 'stories'
    notice = (
        '<tr><td align="center" style="padding:24px 28px;background:#eff6ff;'
        'border-top:1px solid #dbeafe;">'
        '<p style="font-size:15px;color:#1e40af;margin:0 0 6px;font-weight:600;">'
        f'{removed_count} more {story_word} in this brief &mdash; listed above.'
        '</p>'
        '<p style="font-size:13px;color:#3b5bdb;margin:0 0 14px;">'
        'Open the full brief on the web for every story, all sources and the '
        'left / centre / right breakdown.'
        '</p>'
        '<a href="' + web_url + '" target="_blank" '
        'style="display:inline-block;font-size:14px;font-weight:600;color:#ffffff;'
        'background:#1e40af;padding:12px 20px;border-radius:8px;text-decoration:none;">'
        'Read the full brief &rarr;</a></td></tr>'
    )
    for anchor in ('<!--email-trim:lens-check-->', '<!--email-trim:tradeoffs-->', '<!-- Footer -->'):
        idx = html.find(anchor)
        if idx > 0:
            return html[:idx] + notice + html[idx:]
    return html + notice


def _repoint_index_links_to_web(html: str, item_ids, magic_url: str) -> str:
    """Point the headline-index links of collapsed stories at the web brief.

    Their in-page ``#item-N`` anchors were removed with the story bodies, so an
    unrewritten index link would jump nowhere. Rewrite just those to open the
    full brief on the web (still anchored to the story).
    """
    if not magic_url or magic_url == '#':
        return html
    for item_id in item_ids:
        html = html.replace(
            f'href="#item-{item_id}"',
            f'href="{magic_url}#item-{item_id}"',
        )
    return html


def _trim_story_rows_from_end(html: str, limit: int, *, min_rows: int = 3) -> str:
    prefix, rows, suffix = _split_story_rows(html)
    if not rows:
        return html
    original_count = len(rows)
    removed_ids = []

    def _over_budget() -> bool:
        return _email_html_byte_size(prefix + ''.join(rows) + suffix) > limit

    # Prefer keeping at least min_rows full story cards; if still over budget,
    # continue collapsing tail stories down to one so Gmail never clips.
    while len(rows) > min_rows and _over_budget():
        dropped = rows.pop()
        m = re.search(r'id="item-(\d+)"', dropped)
        if m:
            removed_ids.append(m.group(1))
    while len(rows) > 1 and _over_budget():
        dropped = rows.pop()
        m = re.search(r'id="item-(\d+)"', dropped)
        if m:
            removed_ids.append(m.group(1))
    if len(rows) == original_count:
        return html
    trimmed = prefix + ''.join(rows)
    web_url = _web_url_for_trimmed_stories(html)
    trimmed = _repoint_index_links_to_web(trimmed, removed_ids, web_url)
    return _append_read_more_notice(trimmed, original_count - len(rows)) + suffix


def _strip_email_trim_markers(html: str) -> str:
    return re.sub(r'<!--/?email-trim:[^>]+-->\s*', '', html)


def _fit_email_html_to_gmail(html: str, limit: int = GMAIL_CLIP_TARGET_BYTES) -> str:
    """Drop optional sections until HTML fits under Gmail's clip threshold."""
    if _email_html_byte_size(html) <= limit:
        return html
    original_size = _email_html_byte_size(html)
    trimmed_sections = []
    for section_id in _EMAIL_TRIM_ORDER:
        if _email_html_byte_size(html) <= limit:
            break
        next_html = _remove_email_trim_section(html, section_id)
        if next_html != html:
            trimmed_sections.append(section_id)
            html = next_html
    if _email_html_byte_size(html) > limit:
        html, perspectives_removed = _strip_perspectives_from_tail_stories(html, limit)
        if perspectives_removed:
            trimmed_sections.append(f'story-perspectives×{perspectives_removed}')
    if _email_html_byte_size(html) > limit:
        next_html = _trim_story_rows_from_end(html, limit)
        if next_html != html:
            trimmed_sections.append('story-rows')
            html = next_html
    final_size = _email_html_byte_size(html)
    if final_size <= limit:
        logger.info(
            "Daily brief email trimmed %s to fit Gmail limit (%d → %d bytes)",
            ', '.join(trimmed_sections) or 'none',
            original_size,
            final_size,
        )
        return html
    logger.warning(
        "Daily brief email still %d bytes after trimming %s (Gmail clips ~%d); "
        "recipients may see truncated content",
        final_size,
        ', '.join(trimmed_sections) or 'none',
        GMAIL_CLIP_LIMIT_BYTES,
    )
    return html


def _minify_email_html(html: str) -> str:
    html = _RE_HTML_COMMENT.sub('', html)
    html = _RE_CSS_COMMENT.sub('', html)
    html = _RE_BLANK_LINES.sub('\n', html)
    html = _RE_WHITESPACE_BETWEEN_TAGS.sub('><', html)
    html = re.sub(
        r"-apple-system,\s*BlinkMacSystemFont,\s*"
        r"(?:&quot;|')Segoe UI(?:&quot;|'),\s*Roboto,\s*"
        r"(?:&quot;|')Helvetica Neue(?:&quot;|'),\s*Arial,\s*sans-serif",
        _SYSTEM_FONT,
        html,
    )
    html = re.sub(
        r"Georgia,\s*(?:&quot;|')Times New Roman(?:&quot;|'),\s*serif",
        _SERIF_FONT,
        html,
    )
    # _compact_style also strips redundant inline sans-serif copies from each
    # style="..." attribute (scoped there so the <head> <style> font rule survives).
    html = _RE_STYLE_ATTR.sub(_compact_style, html)
    html = _RE_TAG_LINE_INDENT.sub(r'\1', html)
    return html.strip()


def _daily_send_lock_key(target_date=None) -> str:
    """Shared lock key for all daily brief sends on a given date."""
    if target_date is None:
        target_date = utcnow_naive().date()
    return f"brief_send_lock:daily:{target_date.isoformat()}"


def _weekly_send_lock_key(target_date=None, hour=None) -> str:
    """Shared lock key for weekly brief sends in a given UTC hour.

    Scoped per hour rather than per day: weekly subscribers are spread across
    timezones, so each hourly run serves a different cohort and must not be
    blocked by the previous hour's lock.
    """
    now = utcnow_naive()
    if target_date is None:
        target_date = now.date()
    if hour is None:
        hour = now.hour
    return f"brief_send_lock:weekly:{target_date.isoformat()}:{hour}"


def acquire_daily_send_lock(target_date=None, ttl_seconds: int = 3500, lock_key: str = None):
    """
    Acquire Redis lock for brief sending.

    Weekly brief sends use the same policy and the same helper — no REDIS_URL or
    Redis errors mean no send — passing the weekly key via ``lock_key``.

    Args:
        target_date: Date to scope the default (daily) key to.
        ttl_seconds: Lock expiry. A backstop only; the caller must still release
            in a ``finally`` so a fast send does not hold the slot for an hour.
        lock_key: Explicit key, overriding the daily default.

    Returns:
        (acquired, redis_client, lock_key, lock_token, reason)
    """
    redis_url = os.environ.get('REDIS_URL')
    if not redis_url:
        return False, None, None, None, "redis_unavailable"

    lock_key = lock_key or _daily_send_lock_key(target_date)
    lock_token = secrets.token_urlsafe(18)

    try:
        from app.lib.redis_client import get_client
        client = get_client(decode_responses=False)
        if not client:
            return False, None, lock_key, None, "redis_unavailable"
        acquired = client.set(lock_key, lock_token, nx=True, ex=max(30, int(ttl_seconds)))
        if not acquired:
            return False, None, lock_key, None, "lock_held"
        return True, client, lock_key, lock_token, "ok"
    except Exception as e:
        logger.warning(f"Could not acquire daily brief send lock: {e}")
        return False, None, lock_key, None, "redis_error"


def release_daily_send_lock(redis_client, lock_key: str, lock_token: str) -> None:
    """Release lock only if token still matches (safe unlock).

    The token check matters: a PID or hostname is not unique across Render
    instances, so an unconditional DEL could release a lock another worker
    currently holds.
    """
    if not redis_client or not lock_key or not lock_token:
        return
    try:
        redis_client.eval(
            "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) else return 0 end",
            1,
            lock_key,
            lock_token,
        )
    except Exception as e:
        logger.warning(f"Could not release daily brief send lock: {e}")


class ResendClient:
    """
    Resend API client for sending daily brief emails.

    Features:
    - Rate limiting (14 emails/sec)
    - Retry logic with exponential backoff
    - HTML email rendering
    - Error tracking
    """

    API_URL = 'https://api.resend.com/emails'
    RATE_LIMIT = 14  # emails per second
    MAX_RETRIES = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self):
        self._disabled = False
        if not _email_sending_allowed_for_environment():
            logger.warning(
                "Daily brief outbound email disabled outside deployed production. "
                "Set ALLOW_EMAIL_IN_NON_PROD=1 only for intentional testing."
            )
            self._disabled = True

        self.api_key = os.environ.get('RESEND_API_KEY')
        if not self.api_key:
            if self._disabled:
                logger.warning("RESEND_API_KEY not set - daily brief email disabled in non-production.")
            else:
                raise ValueError("RESEND_API_KEY environment variable not set")

        self.rate_limiter = RateLimiter(self.RATE_LIMIT)
        self.last_send_error: Optional[str] = None
        from app.lib.brief_from_email import brief_from_email_address
        self._from_email_addr = brief_from_email_address()
        self.from_email = f'Daily Brief <{self._from_email_addr}>'
        self.reply_to = os.environ.get('BRIEF_REPLY_TO', self._from_email_addr)

    def _extract_email_domain(self, address: Optional[str]) -> str:
        """Extract normalized domain for lightweight deliverability preflight logging."""
        if not address:
            return 'unknown'
        _, parsed_email = parseaddr(address)
        if not parsed_email or '@' not in parsed_email:
            return 'unknown'
        return parsed_email.split('@', 1)[1].lower()

    def _render_brief_text(
        self,
        brief: DailyBrief,
        magic_link_url: str,
        unsubscribe_url: str,
        preferences_url: str,
        sorted_items: Optional[List[BriefItem]] = None,
        web_brief_url: Optional[str] = None,
    ) -> str:
        """Render a plain-text alternative to improve inbox deliverability."""
        if sorted_items is None:
            sorted_items = self._get_sorted_brief_items(brief)

        lines = [
            brief.title or "Daily Brief",
            "",
            f"Date: {brief.date.strftime('%A, %B %d, %Y') if getattr(brief, 'date', None) else 'Today'}",
        ]

        intro_text = getattr(brief, 'intro_text', None)
        if intro_text:
            lines.extend(["", intro_text.strip()])

        lines.extend(["", "Top stories:"])
        for item in sorted_items:
            headline = (item.headline or '').strip()
            if not headline:
                continue
            lines.append(f"{item.position}. {headline}")

            quick_summary = (item.quick_summary or '').strip()
            if quick_summary:
                lines.append(f"   {quick_summary}")

            for bullet in (item.summary_bullets or [])[:3]:
                bullet_text = (bullet or '').strip()
                if bullet_text:
                    lines.append(f"   - {bullet_text}")

            if item.personal_impact:
                lines.append(f"   Why this matters: {item.personal_impact}")
            lines.append("")

        lines.extend([
            f"View on web: {web_brief_url or magic_link_url}",
            f"Manage preferences: {preferences_url}",
            f"Unsubscribe: {unsubscribe_url}",
        ])
        return "\n".join(lines).strip() + "\n"

    def _get_sorted_brief_items(self, brief: DailyBrief) -> List[BriefItem]:
        """Fetch brief items once in position order for reuse across renderers."""
        return list(brief.items.order_by(BriefItem.position.asc()).all())

    def _render_welcome_text(
        self,
        subscriber: DailyBriefSubscriber,
        magic_link_url: str,
        preferences_url: str,
        unsubscribe_url: str,
    ) -> str:
        """Render a plain-text welcome email alternative."""
        cadence_label = 'Weekly Brief' if subscriber.cadence == 'weekly' else 'Daily Brief'
        lines = [
            f"Welcome to Society Speaks {cadence_label}",
            "",
            "Your free access is active.",
            "",
            f"Preferred send hour: {subscriber.preferred_send_hour}:00",
            f"Timezone: {subscriber.timezone}",
            "",
            f"Open your brief: {magic_link_url}",
            f"Manage preferences: {preferences_url}",
            f"Unsubscribe: {unsubscribe_url}",
        ]
        return "\n".join(lines).strip() + "\n"

    def _from_for_brief(self, brief: DailyBrief = None) -> str:
        """Return from address with cadence-appropriate display name."""
        if brief and getattr(brief, 'brief_type', 'daily') == 'weekly':
            return f'Weekly Brief <{self._from_email_addr}>'
        return self.from_email

    def _mark_bounced(self, subscriber: DailyBriefSubscriber, reason: str) -> None:
        """Suppress a subscriber (status='bounced') so no further sends occur."""
        try:
            subscriber.status = 'bounced'
            subscriber.unsubscribed_at = utcnow_naive()
            db.session.commit()
            logger.warning(
                f"Suppressed DailyBriefSubscriber {subscriber.id} <{subscriber.email}> — {reason}"
            )
        except Exception as suppress_err:
            db.session.rollback()
            logger.error(f"Failed to suppress subscriber {subscriber.id}: {suppress_err}")

    def _handle_send_failure(self, subscriber: DailyBriefSubscriber) -> None:
        """Apply per-recipient failure policy after a failed send.

        - invalid_recipient (422): suppress immediately.
        - permanent (e.g. 400): count it; suppress once the threshold is hit so
          a dead address isn't retried on every brief. Warn only — one bad
          recipient must not page.
        - transient: no subscriber-state change; the caller retries.
        """
        classification = classify_send_failure(self.last_send_error)
        if classification == 'invalid_recipient':
            self._mark_bounced(
                subscriber, f"Resend rejected as invalid ({self.last_send_error})"
            )
        elif classification == 'permanent':
            try:
                reached_threshold = subscriber.register_permanent_send_failure()
                db.session.commit()
            except Exception as track_err:
                db.session.rollback()
                logger.error(
                    f"Failed to record send failure for subscriber {subscriber.id}: {track_err}"
                )
                return
            if reached_threshold:
                self._mark_bounced(
                    subscriber,
                    f"{subscriber.send_failure_count} consecutive permanent send "
                    f"failures (last: {truncate_resend_error(self.last_send_error)})",
                )
        # transient: leave subscriber state untouched; send_to_subscribers retries.
        # Permanent/invalid paths: canonical structured log is emitted by
        # send_to_subscribers after send_brief returns (avoids duplicate lines).

    def send_brief(
        self,
        subscriber: DailyBriefSubscriber,
        brief: DailyBrief
    ) -> bool:
        """
        Send brief email to a subscriber.

        Args:
            subscriber: DailyBriefSubscriber instance
            brief: DailyBrief instance to send

        Returns:
            bool: True if sent successfully
        """
        # Reset from any prior call so a stale error from subscriber N-1 cannot
        # bleed into subscriber N when send_brief returns False early (e.g.
        # invalid email) before _send_with_retry ever runs.
        self.last_send_error = None

        try:
            # Validate and normalise the stored address (handles "Name <addr>",
            # bare "<addr>", and other malformed variants) via the shared
            # helper in email_utils.
            cleaned_email = extract_clean_email(subscriber.email)
            if not cleaned_email:
                logger.error(
                    f"Subscriber {subscriber.id} has invalid email: {repr(subscriber.email)} — skipping send"
                )
                return False

            # Pre-fetch once — passed to both HTML and plain-text renderers
            sorted_items = self._get_sorted_brief_items(brief)

            # Build URLs
            base_url = get_base_url()
            magic_link_url = build_brief_magic_link_url(
                base_url, subscriber.magic_token, brief,
            )
            web_brief_url = public_brief_url(base_url, brief)
            unsubscribe_url = build_brief_unsubscribe_url(base_url, subscriber)
            preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"

            # Render email HTML (sorted_items passed to avoid a second DB query)
            html_content = self._render_email(subscriber, brief, sorted_items=sorted_items)

            # Wrap links for click tracking (tracks clicks in EmailEvent)
            secret = current_app.config.get('SECRET_KEY', '')
            html_content = _wrap_links(
                html=html_content,
                base_url=base_url,
                run_id=brief.id,
                r_hash=str(subscriber.id),
                secret=secret,
                track_path='/brief/track/click',
            )
            post_wrap_size = _email_html_byte_size(html_content)
            if post_wrap_size > GMAIL_CLIP_LIMIT_BYTES:
                logger.warning(
                    "Daily brief email is %d bytes after click-tracking wrap "
                    "(Gmail clips ~%d); consider lowering GMAIL_CLIP_TARGET_BYTES",
                    post_wrap_size,
                    GMAIL_CLIP_LIMIT_BYTES,
                )

            # Prepare email data with List-Unsubscribe headers for compliance
            email_data = {
                'from': self._from_for_brief(brief),
                'to': [cleaned_email],
                'subject': brief.title,
                'html': html_content,
                'text': self._render_brief_text(
                    brief=brief,
                    magic_link_url=magic_link_url,
                    unsubscribe_url=unsubscribe_url,
                    preferences_url=preferences_url,
                    sorted_items=sorted_items,
                    web_brief_url=web_brief_url,
                ),
                'reply_to': self.reply_to,
                'tags': [
                    {'name': 'campaign', 'value': 'daily_brief'},
                    {'name': 'brief_type', 'value': getattr(brief, 'brief_type', 'daily')},
                ],
                'headers': {
                    'List-Unsubscribe': f'<{unsubscribe_url}>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click'
                }
            }

            from_domain = self._extract_email_domain(email_data.get('from'))
            reply_to_domain = self._extract_email_domain(email_data.get('reply_to'))
            logger.info(
                "Brief send preflight: from_domain=%s reply_to_domain=%s brief_type=%s",
                from_domain,
                reply_to_domain,
                getattr(brief, 'brief_type', 'daily')
            )

            # Send with rate limiting
            self.rate_limiter.acquire()

            # Stable idempotency key: one brief → one subscriber. Brief HTML is
            # fixed for a given brief id; DB last_brief_id_sent guards restarts.
            send_idempotency_key = scoped_entity_ref('brief', brief.id, subscriber.id)
            success = self._send_with_retry(email_data, idempotency_key=send_idempotency_key)

            if success:
                subscriber.last_sent_at = utcnow_naive()
                subscriber.last_brief_id_sent = brief.id
                subscriber.total_briefs_received += 1
                subscriber.clear_send_failures()
                db.session.commit()
                logger.info(f"Sent brief to {subscriber.email}")
                
                # Record analytics event
                try:
                    from app.lib.email_analytics import EmailAnalytics
                    EmailAnalytics.record_send(
                        email=subscriber.email,
                        category=EmailAnalytics.CATEGORY_DAILY_BRIEF,
                        subject=brief.title,
                        brief_subscriber_id=subscriber.id,
                        brief_id=brief.id
                    )
                except Exception as analytics_error:
                    logger.warning(f"Failed to record analytics for {subscriber.email}: {analytics_error}")
            else:
                self._handle_send_failure(subscriber)

            return success

        except Exception as e:
            # Surface the real error so send_to_subscribers can log it instead of
            # falling back to the generic "Resend: unknown error" placeholder.
            self.last_send_error = str(e)
            try:
                db.session.rollback()
            except Exception:
                pass
            logger.error(
                "Failed to send brief to %s: %s",
                getattr(subscriber, 'email', '<unknown>'),
                e,
                exc_info=True,
                extra={
                    'subscriber_id': getattr(subscriber, 'id', None),
                    'brief_id': getattr(brief, 'id', None),
                },
            )
            return False

    def _send_with_retry(self, email_data: dict, idempotency_key: str = None) -> bool:
        """
        Send a daily brief email via Resend with retry.

        Args:
            email_data: Email payload for Resend API
            idempotency_key: Optional stable key to prevent duplicate delivery on
                             retried 5xx responses. Defaults to a per-attempt key.

        Returns:
            bool: True on success, False on failure
        """
        if self._disabled:
            recipient = (email_data.get('to') or ['unknown'])[0]
            logger.info(f"Daily brief email skipped (non-production guard): {recipient}")
            self.last_send_error = None
            return True

        email_data, resolved_key = ensure_email_idempotency(
            email_data, idempotency_key=idempotency_key, default_prefix='brief'
        )
        success, result = resend_post_with_retry(
            self.api_key,
            email_data,
            max_retries=self.MAX_RETRIES,
            retry_delay=self.RETRY_DELAY,
            idempotency_key=resolved_key,
            warn_statuses=_BRIEF_RESEND_WARN_STATUSES,
            warn_on_retryable=True,
        )
        self.last_send_error = result if not success else None
        return success

    def _render_email(
        self,
        subscriber: DailyBriefSubscriber,
        brief: DailyBrief,
        sorted_items=None,
    ) -> str:
        """
        Render email HTML from template.

        Args:
            subscriber: Subscriber info for personalization
            brief: Brief content to render
            sorted_items: Pre-fetched brief items (avoids a redundant DB query when
                          called from send_brief which already fetches them for the text renderer)

        Returns:
            str: HTML email content
        """
        # Get base URL from config or env
        base_url = get_base_url()

        # Build URLs — pin the magic link to this edition so "view in browser"
        # (and Gmail-trim "read the full brief") open the emailed day, not today.
        magic_link_url = build_brief_magic_link_url(
            base_url, subscriber.magic_token, brief,
        )
        web_brief_url = public_brief_url(base_url, brief)
        unsubscribe_url = build_brief_unsubscribe_url(base_url, subscriber)
        preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"
        if sorted_items is None:
            sorted_items = self._get_sorted_brief_items(brief)

        # Render template
        # Note: This assumes template exists at templates/emails/daily_brief.html
        # DailyBriefSubscriber has no language field; the daily brief is an
        # English-language news product, so we render under the default 'en'
        # locale. Pass None to _render_for_user so it pins the locale
        # explicitly rather than inheriting from an unrelated request context.
        from app.resend_client import _render_for_user as _render_email_for_user
        from app.lib.personal_briefs_cta import (
            personal_briefs_cta_url,
            DEFAULT_TRIAL_TEMPLATE_SLUG,
        )
        # Default to the global trial template for cold-traffic conversion
        # when the self-serve flow is enabled. See build doc Block C item 16.
        personal_briefs_url = personal_briefs_cta_url(
            base_url,
            utm_source='daily_brief',
            utm_medium='email',
            utm_campaign='personal_briefs_cta',
            template_slug=DEFAULT_TRIAL_TEMPLATE_SLUG,
        )
        from app.brief.stance_card import build_stance_email_handoff, build_weekly_stance_email_handoff
        stance_handoff = None
        if brief.brief_type == 'daily':
            stance_handoff = build_stance_email_handoff(
                brief_date=brief.date,
                base_url=base_url,
                subscriber=subscriber,
            )
        elif brief.brief_type == 'weekly':
            week_start = brief.week_start_date or (brief.date - timedelta(days=6))
            week_end = brief.week_end_date or brief.date
            stance_handoff = build_weekly_stance_email_handoff(
                week_start=week_start,
                week_end=week_end,
                week_end_date=brief.date,
                base_url=base_url,
                subscriber=subscriber,
            )
        try:
            html = _render_email_for_user(
                None,
                'emails/daily_brief.html',
                brief=brief,
                sorted_items=sorted_items,
                subscriber=subscriber,
                magic_link_url=magic_link_url,
                web_brief_url=web_brief_url,
                unsubscribe_url=unsubscribe_url,
                preferences_url=preferences_url,
                base_url=base_url,
                personal_briefs_cta_url=personal_briefs_url,
                SECTIONS=SECTIONS,
                TOPIC_DISPLAY_LABELS=TOPIC_DISPLAY_LABELS,
                TOPIC_DISPLAY_COLORS=TOPIC_DISPLAY_COLORS,
                stance_handoff=stance_handoff,
            )
            # Minify first so the size budget is measured against the true wire
            # size. Minify preserves the <!--email-trim:*--> markers and the
            # <tr id="item-N"> row boundaries the fitter relies on; fitting the
            # un-minified HTML (~2.3x larger from indentation) would trim far
            # more content than the sent email actually needs.
            html = _minify_email_html(html)
            html = _fit_email_html_to_gmail(html)
            html = _strip_email_trim_markers(html)
            return html
        except Exception as e:
            logger.error(f"Template rendering failed: {e}")
            # The DB connection may have dropped mid-render (e.g. SSL EOF), leaving
            # the session in an error state. Roll back before the fallback renderer
            # attempts any further queries — otherwise SQLAlchemy raises
            # "Can't reconnect until invalid transaction is rolled back".
            try:
                db.session.rollback()
            except Exception:
                pass
            return self._fallback_html(brief, magic_link_url, unsubscribe_url)

    def _fallback_html(self, brief: DailyBrief, magic_link_url: str, unsubscribe_url: str) -> str:
        """
        Generate simple HTML email if template rendering fails.

        Args:
            brief: DailyBrief instance
            magic_link_url: Magic link to view brief on website
            unsubscribe_url: Unsubscribe link

        Returns:
            str: Simple HTML email
        """
        items_html = ""
        try:
            brief_items = self._get_sorted_brief_items(brief)
        except Exception as e:
            logger.warning(f"Fallback HTML: could not fetch brief items ({e}), sending items-free fallback")
            brief_items = []
        for item in brief_items:
            bullets_html = "".join([f"<li>{bullet}</li>" for bullet in (item.summary_bullets or [])])
            items_html += f"""
            <div style="margin-bottom: 30px; padding: 20px; background: #f9f9f9; border-left: 4px solid #333;">
                <h2 style="margin: 0 0 10px 0; font-size: 18px;">{item.position}. {item.headline}</h2>
                <ul style="margin: 10px 0; padding-left: 20px;">
                    {bullets_html}
                </ul>
                <p style="margin: 10px 0 5px 0; font-size: 12px; color: #666;">
                    Coverage: {item.source_count} sources
                </p>
            </div>
            """

        # Read brief scalar attributes defensively: after a DB error + rollback
        # SQLAlchemy marks ORM attributes as expired and will re-query them on
        # access.  If the connection is still unstable that triggers a second
        # exception inside this fallback.  getattr with safe defaults prevents
        # the fallback itself from crashing and ensures the subscriber always
        # gets at least a minimal email they can click through on.
        brief_title = getattr(brief, 'title', None) or 'Daily Brief'
        brief_date = getattr(brief, 'date', None)
        brief_date_str = brief_date.strftime('%A, %B %d, %Y') if brief_date else ''
        brief_intro = getattr(brief, 'intro_text', None) or ''

        html = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>{brief_title}</title>
        </head>
        <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
            <div style="text-align: center; border-bottom: 2px solid #333; padding-bottom: 20px; margin-bottom: 30px;">
                <h1 style="margin: 0; font-size: 24px;">SOCIETY SPEAKS DAILY BRIEF</h1>
                <p style="margin: 5px 0 0 0; font-size: 14px; color: #666;">{brief_date_str}</p>
            </div>

            <div style="text-align: center; margin-bottom: 25px;">
                <a href="{public_brief_url(get_base_url(), brief)}" style="display: inline-block; background-color: #d97706; color: #ffffff; text-decoration: none; padding: 12px 24px; border-radius: 6px; font-weight: 600; font-size: 14px;">View on Website</a>
            </div>

            <div style="margin-bottom: 30px; padding: 15px; background: #fffbf0; border-left: 4px solid #f0ad4e;">
                <p style="margin: 0; font-size: 14px; font-style: italic;">
                    {brief_intro}
                </p>
            </div>

            {items_html}

            <div style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #ddd; font-size: 12px; color: #666; text-align: center;">
                <p><a href="{public_brief_url(get_base_url(), brief)}" style="color: #d97706; font-weight: 600;">View on Website</a> | <a href="{unsubscribe_url}" style="color: #666;">Unsubscribe</a> | <a href="https://societyspeaks.io/brief/archive" style="color: #666;">View Archive</a></p>
                <p style="margin-top: 10px;">Society Speaks – Sense-making, not sensationalism</p>
            </div>
        </body>
        </html>
        """
        return html

    def send_welcome(self, subscriber: DailyBriefSubscriber, force: bool = False) -> bool:
        """
        Send welcome email to new daily brief subscriber.

        Args:
            subscriber: DailyBriefSubscriber instance
            force: If True, send even if welcome email was already sent (for manual resends)

        Returns:
            bool: True if sent successfully
        """
        try:
            # Safety check: prevent duplicate welcome emails
            if subscriber.welcome_email_sent_at and not force:
                logger.warning(f"Welcome email already sent to {subscriber.email} at {subscriber.welcome_email_sent_at}, skipping (use force=True to override)")
                return True  # Return True since email was already sent successfully

            base_url = get_base_url()

            magic_link_url = f"{base_url}/brief/m/{subscriber.magic_token}"
            preferences_url = f"{base_url}/brief/preferences/{subscriber.magic_token}"
            unsubscribe_url = build_brief_unsubscribe_url(base_url, subscriber)

            from app.resend_client import _render_for_user as _render_email_for_user, _subject_for_user as _subject_email_for_user
            html_content = _render_email_for_user(
                None,
                'emails/daily_brief_welcome.html',
                subscriber=subscriber,
                magic_link_url=magic_link_url,
                preferences_url=preferences_url,
                unsubscribe_url=unsubscribe_url,
                base_url=base_url,
                preferred_hour=subscriber.preferred_send_hour,
                timezone=subscriber.timezone,
            )

            cadence_label = _subject_email_for_user(None, 'Weekly Brief') if subscriber.cadence == 'weekly' else _subject_email_for_user(None, 'Daily Brief')
            subject = _subject_email_for_user(None, 'Welcome to the %(label)s - Your Free Access is Active!', label=cadence_label)

            email_data = {
                'from': self.from_email,
                'to': [subscriber.email],
                'subject': subject,
                'html': html_content,
                'text': self._render_welcome_text(
                    subscriber=subscriber,
                    magic_link_url=magic_link_url,
                    preferences_url=preferences_url,
                    unsubscribe_url=unsubscribe_url,
                ),
                'reply_to': self.reply_to,
                'tags': [
                    {'name': 'campaign', 'value': 'brief_welcome'},
                    {'name': 'cadence', 'value': subscriber.cadence or 'daily'},
                ],
            }

            self.rate_limiter.acquire()
            # Per-attempt key: business "send welcome once" is enforced by
            # welcome_email_sent_at, not a forever-stable Resend key (template /
            # From drift within 24h would otherwise 409).
            welcome_idempotency_key = send_attempt_entity_ref(
                'brief-welcome', subscriber.id
            )
            success = self._send_with_retry(
                email_data,
                idempotency_key=welcome_idempotency_key,
            )

            if success:
                # Record that welcome email was sent to prevent duplicates
                subscriber.welcome_email_sent_at = utcnow_naive()
                db.session.commit()
                logger.info(f"Sent welcome email to {subscriber.email}")
            else:
                logger.error(f"Failed to send welcome email to {subscriber.email}")

            return success

        except Exception as e:
            logger.error(f"Error sending welcome email to {subscriber.email}: {e}")
            return False

    def send_unsubscribe_recovery(self, subscriber: DailyBriefSubscriber) -> bool:
        """Email a fresh stable unsubscribe link after an invalid/expired email link."""
        try:
            base_url = get_base_url()
            unsubscribe_url = build_brief_unsubscribe_url(base_url, subscriber)
            cadence_label = 'Weekly Brief' if subscriber.cadence == 'weekly' else 'Daily Brief'
            subject = f'Unsubscribe from Society Speaks {cadence_label}'
            text = (
                f"You asked to unsubscribe from the Society Speaks {cadence_label}.\n\n"
                f"Use this link to confirm:\n{unsubscribe_url}\n\n"
                "If you did not request this, you can ignore this message."
            )
            email_data = {
                'from': self.from_email,
                'to': [subscriber.email],
                'subject': subject,
                'text': text,
                'headers': {
                    'List-Unsubscribe': f'<{unsubscribe_url}>',
                    'List-Unsubscribe-Post': 'List-Unsubscribe=One-Click',
                },
                'tags': [{'name': 'campaign', 'value': 'brief_unsubscribe_recovery'}],
            }
            self.rate_limiter.acquire()
            recovery_key = send_attempt_entity_ref('brief-unsub-recover', subscriber.id)
            success = self._send_with_retry(email_data, idempotency_key=recovery_key)
            if success:
                logger.info('Sent brief unsubscribe recovery to %s', subscriber.email)
            else:
                logger.error('Failed to send brief unsubscribe recovery to %s', subscriber.email)
            return success
        except Exception as exc:
            logger.error('Error sending brief unsubscribe recovery to %s: %s', subscriber.email, exc)
            return False


class BriefEmailScheduler:
    """
    Manages timezone-based email sending for daily brief.

    Sends emails at subscriber's preferred hour in their timezone.
    """

    def __init__(self):
        self.client = ResendClient()

    def get_subscribers_for_hour(self, utc_hour: int, cadence: str = 'daily', brief_id: int = None) -> List[DailyBriefSubscriber]:
        """
        Get subscribers who should receive email at this UTC hour.

        Args:
            utc_hour: Current UTC hour (0-23)
            cadence: 'daily' or 'weekly' — filters by subscriber preference
            brief_id: Optional brief ID for DB-level idempotency check

        Returns:
            List of DailyBriefSubscriber instances
        """
        query = DailyBriefSubscriber.query.filter(
            DailyBriefSubscriber.status == 'active'
        )

        # Filter by cadence preference
        if cadence == 'weekly':
            query = query.filter(DailyBriefSubscriber.cadence == 'weekly')
        else:
            # Daily subscribers: include those without cadence set (backward compat)
            query = query.filter(
                db.or_(
                    DailyBriefSubscriber.cadence == 'daily',
                    DailyBriefSubscriber.cadence == None
                )
            )

        all_subscribers = query.all()

        subscribers_to_send = []

        for subscriber in all_subscribers:
            if not subscriber.can_receive_brief(brief_id=brief_id):
                continue

            # For weekly: also check it's their preferred day
            if cadence == 'weekly':
                now_utc = utcnow_naive().replace(tzinfo=pytz.utc)
                try:
                    local_tz = pytz.timezone(subscriber.timezone)
                    now_local = now_utc.astimezone(local_tz)
                    preferred_day = getattr(subscriber, 'preferred_weekly_day', 6) or 6
                    if now_local.weekday() != preferred_day:
                        continue
                except Exception as e:
                    logger.error(f"Timezone error for {subscriber.email}: {e}")
                    continue

            # Convert subscriber's preferred time to UTC
            try:
                local_tz = pytz.timezone(subscriber.timezone)
                now_utc = utcnow_naive().replace(tzinfo=pytz.utc)
                now_local = now_utc.astimezone(local_tz)

                # Check if it's their preferred send hour in their timezone,
                # or within a 2-hour catch-up window for missed sends.
                # can_receive_brief (checked above) prevents any duplicates.
                CATCHUP_HOURS = 2
                hours_since_preferred = (now_local.hour - subscriber.preferred_send_hour) % 24
                if hours_since_preferred <= CATCHUP_HOURS:
                    if hours_since_preferred > 0:
                        logger.info(
                            f"Catch-up send: subscriber {subscriber.id} missed their "
                            f"{subscriber.preferred_send_hour:02d}:00 window by {hours_since_preferred}h"
                        )
                    subscribers_to_send.append(subscriber)

            except Exception as e:
                logger.error(f"Timezone error for {subscriber.email}: {e}")
                continue

        logger.info(f"Found {len(subscribers_to_send)} {cadence} subscribers for hour {utc_hour}")
        return subscribers_to_send

    def _release_claim(self, subscriber_id, brief_id, prev_brief_id, prev_sent_at):
        """Undo a send claim after a failed send so catch-up runs can retry.

        Conditional on the claim still being ours (last_brief_id_sent ==
        brief_id) so we never clobber a claim a concurrent loop later won.
        Never raises — the send error being handled takes precedence.
        """
        try:
            DailyBriefSubscriber.query.filter(
                DailyBriefSubscriber.id == subscriber_id,
                DailyBriefSubscriber.last_brief_id_sent == brief_id,
            ).update(
                {'last_brief_id_sent': prev_brief_id, 'last_sent_at': prev_sent_at},
                synchronize_session=False,
            )
            db.session.commit()
        except Exception as release_err:
            db.session.rollback()
            logger.error(
                f"Failed to release send claim for subscriber {subscriber_id}: {release_err}"
            )

    def send_to_subscribers(
        self,
        subscribers: List[DailyBriefSubscriber],
        brief: DailyBrief
    ) -> dict:
        """
        Send brief to list of subscribers.

        Args:
            subscribers: List of DailyBriefSubscriber instances
            brief: DailyBrief to send

        Returns:
            dict: {'sent': int, 'failed': int, 'errors': list}
        """
        results = {
            'sent': 0,
            'failed': 0,
            'errors': [],
            'failures': [],
        }

        for subscriber in subscribers:
            subscriber_id = getattr(subscriber, 'id', None)
            claim_committed = False
            prev_brief_id = None
            prev_sent_at = None
            try:
                # Re-fetch latest subscriber state before each send to reduce race risk.
                current_subscriber = DailyBriefSubscriber.query.filter_by(
                    id=subscriber_id
                ).with_for_update().first()

                if not current_subscriber:
                    results['failed'] += 1
                    results['errors'].append(f"Subscriber {subscriber_id} no longer exists")
                    db.session.rollback()
                    continue

                email_str = extract_clean_email(str(current_subscriber.email or ''))
                if not email_str:
                    results['failed'] += 1
                    results['errors'].append(
                        f"Subscriber {current_subscriber.id} has invalid email: {repr(current_subscriber.email)}"
                    )
                    logger.error(
                        f"Skipping subscriber {current_subscriber.id} — invalid email: {repr(current_subscriber.email)}"
                    )
                    db.session.rollback()
                    continue

                if not current_subscriber.can_receive_brief(brief_id=brief.id):
                    db.session.rollback()
                    continue

                if not current_subscriber.magic_token or (
                    current_subscriber.magic_token_expires and current_subscriber.magic_token_expires < utcnow_naive()
                ):
                    current_subscriber.generate_magic_token(expires_hours=168)

                # Ensure every subscriber has a stable unsubscribe token before
                # their email goes out. Idempotent — only writes if token is None.
                current_subscriber.ensure_unsubscribe_token()

                # Atomically claim this (subscriber, brief) pair BEFORE sending.
                # The row lock above is released at the first commit inside the
                # send path, so two concurrent loops (deploy-overlap zombie,
                # catch-up run, manual resume) can otherwise both pass the
                # check and double-send — observed 2026-07-12 (295 duplicate
                # send records). A conditional UPDATE makes exactly one loop
                # win; a crash after claiming skips one day for that subscriber
                # instead of ever duplicating.
                prev_brief_id = current_subscriber.last_brief_id_sent
                prev_sent_at = current_subscriber.last_sent_at
                try:
                    claimed = DailyBriefSubscriber.query.filter(
                        DailyBriefSubscriber.id == current_subscriber.id,
                        db.or_(
                            DailyBriefSubscriber.last_brief_id_sent.is_(None),
                            DailyBriefSubscriber.last_brief_id_sent != brief.id,
                        ),
                    ).update(
                        {'last_brief_id_sent': brief.id, 'last_sent_at': utcnow_naive()},
                        synchronize_session=False,
                    ) == 1
                    # Commit persists the claim and any tokens generated above,
                    # so links in the email always match the database.
                    db.session.commit()
                    claim_committed = claimed
                except Exception as claim_err:
                    db.session.rollback()
                    results['failed'] += 1
                    err_msg = f"Claim failed for subscriber {current_subscriber.id}: {claim_err}"
                    results['errors'].append(err_msg)
                    logger.error(err_msg, exc_info=True)
                    continue

                if not claimed:
                    continue  # another send loop owns this subscriber+brief

                # Isolate Sentry tags per recipient. Hub-level set_tag leaked
                # the *last* subscriber onto the batch summary (PYTHON-FLASK-JF
                # was tagged 2456 after 4188 was the one that failed).
                sentry_scope = (
                    _sentry_sdk.new_scope() if _sentry_sdk else nullcontext()
                )
                with sentry_scope as scope:
                    if scope is not None:
                        scope.set_tag('brief_subscriber_id', current_subscriber.id)
                        scope.set_tag('brief_id', getattr(brief, 'id', None))

                    success = self.client.send_brief(current_subscriber, brief)
                    if success:
                        results['sent'] += 1
                    else:
                        results['failed'] += 1
                        resend_error = getattr(self.client, 'last_send_error', None) or 'unknown error'
                        db.session.rollback()
                        # Re-fetch after send_brief may have committed failure counters /
                        # suppression so logs and batch results reflect persisted state.
                        refreshed = db.session.get(DailyBriefSubscriber, current_subscriber.id)
                        failure_record = build_send_failure_record(
                            subscriber_id=current_subscriber.id,
                            email=current_subscriber.email,
                            brief_id=getattr(brief, 'id', None),
                            resend_error=resend_error,
                            send_failure_count=(
                                refreshed.send_failure_count if refreshed else 0
                            ),
                        )
                        results['failures'].append(failure_record)
                        results['errors'].append(format_send_failure_message(failure_record))
                        log_send_failure(failure_record)
                        if failure_record['pageable']:
                            # Genuine transient/infra failure (retries already exhausted
                            # in the client) — release the claim so a catch-up run picks
                            # this subscriber up again.
                            self._release_claim(
                                current_subscriber.id, brief.id, prev_brief_id, prev_sent_at
                            )

            except Exception as e:
                db.session.rollback()
                results['failed'] += 1
                # Use subscriber_id (captured before the re-fetch) so the log
                # is useful even if current_subscriber was never assigned or its
                # .email attribute was what caused the failure.
                error_msg = f"Error sending to subscriber {subscriber_id}: {str(e)}"
                results['errors'].append(error_msg)
                logger.error(error_msg, exc_info=True)
                # If the claim had been committed before the failure, release
                # it so a later catch-up run can retry this subscriber.
                if claim_committed:
                    self._release_claim(subscriber_id, brief.id, prev_brief_id, prev_sent_at)

        logger.info(
            'Batch send complete: %d sent, %d failed',
            results['sent'],
            results['failed'],
        )
        return results

    def send_todays_brief_hourly(self) -> Optional[dict]:
        """
        Send the latest published daily brief to eligible subscribers this hour.

        Called every hour by the scheduler. Each subscriber is matched to their
        preferred local send hour (see get_subscribers_for_hour); the edition
        delivered is always the newest *published* daily brief
        (DailyBrief.get_latest_published), so which edition a reader gets depends
        on *when* they are eligible, not on a fixed UTC publish-hour cutover.
        Before today's edition is published, "latest published" is naturally the
        prior edition — with graceful degradation if generation is late/failed.

        Returns:
            dict: Send results, or None if no brief published
        """
        from datetime import date

        current_hour = utcnow_naive().hour
        today = date.today()
        lock_acquired, lock_client, lock_key, lock_token, lock_reason = acquire_daily_send_lock(
            target_date=today,
            ttl_seconds=3500
        )
        if not lock_acquired:
            if lock_reason == "lock_held":
                logger.info("Daily brief send already in progress (shared lock held), skipping")
            else:
                logger.error("Daily brief send lock unavailable; skipping send to prevent duplicates")
            return {'sent': 0, 'failed': 0, 'errors': []}

        try:
            # Always send the newest *published* daily brief (see
            # DailyBrief.get_latest_published). This removes the fragile 18:00-UTC
            # magic-hour cutover, degrades gracefully when generation is late or
            # fails (subscribers get the prior edition, never nothing or an
            # unpublished draft), and — with per-brief-id + local-day dedup in
            # can_receive_brief — lets each timezone receive the freshest edition
            # once, at their local hour. Which edition a given reader gets is
            # therefore decided by *when* they are eligible, not by a UTC cutover.
            brief = DailyBrief.get_latest_published(brief_type='daily')

            if not brief:
                logger.info("No published daily brief available, skipping send")
                return None

            subscribers = self.get_subscribers_for_hour(current_hour, cadence='daily', brief_id=brief.id)

            if not subscribers:
                logger.info(f"No daily subscribers for hour {current_hour}")
                return {'sent': 0, 'failed': 0, 'errors': []}

            results = self.send_to_subscribers(subscribers, brief)
            return _attach_brief_send_metadata(results, brief, cadence='daily')
        finally:
            release_daily_send_lock(lock_client, lock_key, lock_token)

    def send_weekly_brief_hourly(self) -> Optional[dict]:
        """
        Send the latest weekly brief to weekly subscribers at current UTC hour.

        Called every hour by scheduler. Only delivers on the subscriber's
        preferred weekly day. Prevents re-sending the same weekly brief
        by checking if the brief was created within the last 7 days.

        **Redis is required** (REDIS_URL): same fail-closed policy as daily brief
        sends — without a distributed lock, multiple workers could duplicate weekly
        deliveries. If Redis is down or misconfigured, we skip and log.

        Returns:
            dict: Send results, or None if no weekly brief available
        """
        from datetime import date, timedelta

        current_hour = utcnow_naive().hour
        today = date.today()

        # Same acquire/release helpers as the daily send: a random token (not a
        # PID, which is not unique across Render instances) and an explicit
        # release, so a completed send frees the slot instead of holding it for
        # the full TTL and blocking any retry within the hour.
        lock_acquired, lock_client, lock_key, lock_token, lock_reason = acquire_daily_send_lock(
            ttl_seconds=3500,
            lock_key=_weekly_send_lock_key(today, current_hour),
        )
        if not lock_acquired:
            if lock_reason == "lock_held":
                logger.info(
                    f"Weekly brief send already in progress for hour {current_hour} "
                    f"(lock held), skipping"
                )
            else:
                logger.error(
                    "Weekly brief send lock unavailable "
                    "(distributed lock required — same policy as daily brief sends); "
                    "skipping send to prevent duplicates"
                )
            return {'sent': 0, 'failed': 0, 'errors': []}

        try:
            # Find the most recent weekly brief
            brief = DailyBrief.query.filter(
                DailyBrief.brief_type == 'weekly',
                DailyBrief.status.in_(['ready', 'published'])
            ).order_by(DailyBrief.date.desc()).first()

            if not brief:
                logger.debug("No published weekly brief available")
                return None

            # Prevent re-sending old weekly briefs: only send if created within last 7 days
            if brief.date <= date.today() - timedelta(days=7):
                logger.debug(f"Weekly brief ({brief.date}) is older than 7 days, skipping")
                return None

            subscribers = self.get_subscribers_for_hour(
                current_hour, cadence='weekly', brief_id=brief.id
            )

            if not subscribers:
                return {'sent': 0, 'failed': 0, 'errors': []}

            logger.info(f"Sending weekly brief ({brief.date}) to {len(subscribers)} subscribers")
            results = self.send_to_subscribers(subscribers, brief)
            return _attach_brief_send_metadata(results, brief, cadence='weekly')
        finally:
            release_daily_send_lock(lock_client, lock_key, lock_token)


def send_brief_to_subscriber(
    subscriber_email: str,
    brief_date: Optional[str] = None,
    brief_type: str = 'daily',
    *,
    allow_unpublished: bool = False,
) -> bool:
    """
    Convenience function to send brief to a single subscriber.

    Args:
        subscriber_email: Email address
        brief_date: Date string (YYYY-MM-DD), or None for the latest edition
        brief_type: 'daily' or 'weekly'. Must be passed explicitly for weekly —
            a weekly brief shares its date with that day's daily edition, so
            defaulting to 'daily' would silently deliver the wrong one.
        allow_unpublished: Admin test paths set this to send a 'ready' edition
            that has not been published yet — the point of a test send is to
            see the email *before* it goes to the list.

    Returns:
        bool: Success status
    """
    if brief_type not in ('daily', 'weekly'):
        logger.error(f"Invalid brief_type: {brief_type!r}")
        return False

    subscriber = DailyBriefSubscriber.query.filter_by(email=subscriber_email).first()
    if not subscriber:
        logger.error(f"Subscriber not found: {subscriber_email}")
        return False

    # Verify subscriber status (allow test sends even if already sent today)
    if subscriber.status != 'active':
        logger.error(f"Subscriber not active: {subscriber_email} (status: {subscriber.status})")
        return False

    if brief_date:
        brief_date_obj = datetime.strptime(brief_date, '%Y-%m-%d').date()
        brief = DailyBrief.get_by_date(
            brief_date_obj,
            brief_type=brief_type,
            published_only=not allow_unpublished,
        )
    else:
        # No explicit date → the current edition = the latest published brief
        # (get_today() is None for most of the UTC day, before generation).
        brief = DailyBrief.get_latest_published(brief_type=brief_type)
        if not brief and allow_unpublished:
            brief = (
                DailyBrief.query
                .filter_by(brief_type=brief_type, status='ready')
                .order_by(DailyBrief.date.desc())
                .first()
            )

    if not brief:
        logger.error(
            f"No {brief_type} brief found for date: {brief_date or 'latest'}"
        )
        return False

    client = ResendClient()
    return client.send_brief(subscriber, brief)
