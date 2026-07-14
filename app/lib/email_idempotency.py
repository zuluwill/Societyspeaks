"""Resend Idempotency-Key helpers (single source of truth).

Resend semantics (24h window on POST /emails and /emails/batch):

- same key + same body → cached success, no duplicate send
- same key + different body → 409 ``invalid_idempotent_request`` (do not retry)
- same key in flight → 409 ``concurrent_idempotent_requests`` (safe to retry)

Key design rules we follow everywhere:

1. The key identifies **one logical payload**, not just a user or calendar bucket.
2. Build the key once with the payload; HTTP retries must reuse it unchanged.
3. Prefer a content/token hash when the send has a stable natural id; otherwise
   use a per-attempt UUID so legitimate resends never collide with a prior body.
4. Never truncate itsdangerous tokens (``token[:16]``) — they share a long
   common prefix for the same ``user_id``.
5. Keys must be latin-1-safe and ≤256 chars — free-form strings (org names,
   messages) are fingerprinted, never interpolated raw into the header.
"""

from __future__ import annotations

import hashlib
import re
import uuid
from typing import Any, Dict, Optional, Sequence, Tuple

_SAFE_ENTITY_ID = re.compile(r'^[A-Za-z0-9._-]{1,64}$')


def content_fingerprint(parts: Sequence[Any], *, length: int = 16) -> str:
    """Stable short hash of payload-defining parts (ids, tokens, etc.)."""
    material = ','.join(str(p) for p in parts)
    return hashlib.sha256(material.encode('utf-8')).hexdigest()[:length]


def _safe_entity_id(entity_id: Any) -> str:
    """Return a header-safe entity fragment (ascii, short); else fingerprint."""
    if entity_id is None:
        return 'na'
    text = str(entity_id)
    if _SAFE_ENTITY_ID.match(text):
        return text
    return content_fingerprint([text])


def token_entity_ref(prefix: str, entity_id: Any, token: str) -> str:
    """Key for sends whose token uniquely identifies the payload (e.g. magic-login)."""
    digest = hashlib.sha256(token.encode('utf-8')).hexdigest()[:32]
    return f'{prefix}:{_safe_entity_id(entity_id)}:{digest}'


def send_attempt_entity_ref(prefix: str, entity_id: Any = None) -> str:
    """Key for one logical send attempt (UUID generated once per payload build).

    Use when auth tokens are deterministic per user, or when the body is ad-hoc
    and must not collide with an earlier attempt inside Resend's 24h window.
    """
    nonce = uuid.uuid4().hex
    if entity_id is None:
        return f'{prefix}:{nonce}'
    return f'{prefix}:{_safe_entity_id(entity_id)}:{nonce}'


def scoped_entity_ref(prefix: str, *parts: Any) -> str:
    """Join prefix + parts into a Resend key (caller supplies uniqueness)."""
    safe_parts = [_safe_entity_id(p) for p in parts]
    return f"{prefix}:{':'.join(safe_parts)}"


def url_token_segment(url: str) -> str:
    """Last path segment of ``url``, stripping query string / fragment."""
    path = url.rstrip('/').rsplit('/', 1)[-1]
    return path.split('?', 1)[0].split('#', 1)[0]


def ensure_email_idempotency(
    email_data: Dict[str, Any],
    *,
    idempotency_key: Optional[str] = None,
    default_prefix: str = 'send',
) -> Tuple[Dict[str, Any], str]:
    """Ensure ``email_data`` carries ``X-Entity-Ref-ID`` and return ``(data, key)``.

    Preference order: explicit ``idempotency_key`` → existing header → new attempt.
    Always mirrors the chosen key into ``X-Entity-Ref-ID`` so ESP-side and HTTP-side
    dedupe stay aligned.
    """
    headers = dict(email_data.get('headers') or {})
    key = (idempotency_key or headers.get('X-Entity-Ref-ID') or '').strip() or None
    if not key:
        key = send_attempt_entity_ref(default_prefix)
    headers['X-Entity-Ref-ID'] = key
    return {**email_data, 'headers': headers}, key
