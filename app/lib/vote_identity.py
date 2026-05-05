"""
Unified pseudonymous voter identity for Society Speaks.

Academic / analytical rigour requires one stable fingerprint per browser across:
- Native statement voting (`statements` blueprint)
- Daily question flows (`daily` blueprint)
- StatementVote rows synced from daily → discussions

Legacy code used separate cookies (`statement_client_id` vs `daily_client_id`), which
split one person into two anonymous participants. We now:

1. Prefer a canonical cookie (`ss_voter_client_id`), falling back to legacy cookies.
2. Write all three names to the same raw client id so browsers converge.
3. Expose alias fingerprints so historical DailyQuestionResponse rows still dedupe.

Methodological note: fingerprints identify browsers / embed-supplied pseudonyms, not
unique humans. Cross-device participation appears as multiple participants unless
the user signs in (anonymous votes merge on login/register).

Read paths that resolve "this visitor's" votes should prefer
``anonymous_fingerprint_aliases_for_daily_lookup()`` so legacy cookie namespaces and
embed fingerprints stay consistent with StatementVote rows; see
``adr/0001-published-vs-audit-vote-semantics.md`` (repo root) for published vs audit counts.
"""

from __future__ import annotations

import hashlib
import secrets
from typing import List

from flask import request, session
from flask_login import current_user

# Canonical first-party voter cookie (new). Legacy names kept for backward compatibility.
VOTER_CANONICAL_COOKIE_NAME = "ss_voter_client_id"
LEGACY_STATEMENT_CLIENT_COOKIE_NAME = "statement_client_id"
LEGACY_DAILY_CLIENT_COOKIE_NAME = "daily_client_id"

VOTER_CLIENT_COOKIE_MAX_AGE = 365 * 24 * 60 * 60
_CLIENT_ID_HEX_LEN = 64


def _raw_client_ids_from_request() -> List[str]:
    """Distinct valid raw client ids present on the request (canonical + legacy order)."""
    out: List[str] = []
    seen = set()
    for name in (
        VOTER_CANONICAL_COOKIE_NAME,
        LEGACY_STATEMENT_CLIENT_COOKIE_NAME,
        LEGACY_DAILY_CLIENT_COOKIE_NAME,
    ):
        cid = request.cookies.get(name)
        if cid and len(cid) == _CLIENT_ID_HEX_LEN and cid not in seen:
            seen.add(cid)
            out.append(cid)
    return out


def get_or_create_voter_client_id() -> tuple[str, bool]:
    """
    Stable raw client id for this anonymous visitor.

    Priority: canonical cookie → statement legacy → daily legacy → fresh random id.
    Returns (client_id_hex_64, is_newly_generated).
    """
    for name in (
        VOTER_CANONICAL_COOKIE_NAME,
        LEGACY_STATEMENT_CLIENT_COOKIE_NAME,
        LEGACY_DAILY_CLIENT_COOKIE_NAME,
    ):
        cid = request.cookies.get(name)
        if cid and len(cid) == _CLIENT_ID_HEX_LEN:
            return cid, False
    return secrets.token_hex(32), True


def fingerprint_from_client_id(client_id: str) -> str:
    """SHA-256 hex digest stored on StatementVote.session_fingerprint / daily responses."""
    return hashlib.sha256(client_id.encode()).hexdigest()


def get_voter_fingerprint() -> str:
    """
    Pseudonymous fingerprint for the current anonymous visitor.

    Syncs Flask session keys used historically (`statement_vote_fingerprint`,
    `daily_fingerprint`) so older session reads stay coherent.
    """
    client_id, __ = get_or_create_voter_client_id()
    fp = fingerprint_from_client_id(client_id)
    if session.get("statement_vote_fingerprint") != fp:
        session["statement_vote_fingerprint"] = fp
        session.modified = True
    if session.get("daily_fingerprint") != fp:
        session["daily_fingerprint"] = fp
        session.modified = True
    if session.get("fingerprint") != fp:
        session["fingerprint"] = fp
        session.modified = True
    return fp


def _maybe_append_embed_fingerprint(fps: List[str], seen: set[str]) -> None:
    """Partner/embed requests may carry embed_fingerprint without first-party cookies."""
    try:
        from app.discussions.statements import extract_embed_fingerprint_from_request

        ef = extract_embed_fingerprint_from_request()
        if ef and ef not in seen:
            seen.add(ef)
            fps.append(ef)
    except Exception:
        return


def anonymous_fingerprint_aliases_for_daily_lookup() -> List[str]:
    """
    Fingerprints that may appear on StatementVote and DailyQuestionResponse rows for this visitor.

    Covers legacy cookie namespaces (daily vs statement) before responses unified cookies,
    the canonical unified fingerprint, and an optional ``embed_fingerprint`` on the request.
    """
    fps: List[str] = []
    seen = set()
    for cid in _raw_client_ids_from_request():
        fp = fingerprint_from_client_id(cid)
        if fp not in seen:
            seen.add(fp)
            fps.append(fp)
    unified = get_voter_fingerprint()
    if unified not in seen:
        seen.add(unified)
        fps.append(unified)
    _maybe_append_embed_fingerprint(fps, seen)
    return fps


def fingerprints_for_anonymous_merge_on_login() -> List[str]:
    """
    All StatementVote anonymous fingerprints to merge when the user logs in.

    Includes session hints, legacy cookie-derived hashes, and embed-supplied fingerprint when present on the request.
    """
    fps: List[str] = []
    seen = set()
    for key in ("statement_vote_fingerprint", "daily_fingerprint", "fingerprint"):
        fp = session.get(key)
        if fp and isinstance(fp, str) and fp not in seen:
            seen.add(fp)
            fps.append(fp)
    for cid in _raw_client_ids_from_request():
        fp = fingerprint_from_client_id(cid)
        if fp not in seen:
            seen.add(fp)
            fps.append(fp)
    _maybe_append_embed_fingerprint(fps, seen)
    return fps


def set_voter_client_cookies_if_needed(response):
    """
    Persist voter client id across all cookie names so surfaces converge.

    Called from anonymous `after_request` hooks on voting-related blueprints.
    """
    if current_user.is_authenticated:
        return response
    client_id, __ = get_or_create_voter_client_id()
    kwargs = {
        "max_age": VOTER_CLIENT_COOKIE_MAX_AGE,
        "httponly": True,
        "secure": True,
        "samesite": "Lax",
    }
    response.set_cookie(VOTER_CANONICAL_COOKIE_NAME, client_id, **kwargs)
    response.set_cookie(LEGACY_STATEMENT_CLIENT_COOKIE_NAME, client_id, **kwargs)
    response.set_cookie(LEGACY_DAILY_CLIENT_COOKIE_NAME, client_id, **kwargs)
    return response
