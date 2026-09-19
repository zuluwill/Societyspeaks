"""
Scored filter for unsolicited marketplace / contact-spam on user-authored
discussion text (statements and responses).

A single keyword is never enough: civic comments routinely mention WhatsApp,
Telegram, marijuana policy, or Kazakhstan. We only reject when several
independent solicitation signals land together.

The public message must stay generic so operators do not teach the next
campaign which tokens we look for.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import re

from flask import current_app

# Reject when the combined score reaches this (overridable via config).
DEFAULT_SCORE_THRESHOLD = 6

_CONTACT_CHANNEL_RE = re.compile(
    r'\b(?:whats?app|telegram|signal|wechat|wickr|kik)\b',
    re.IGNORECASE,
)
_PHONE_RE = re.compile(
    r'(?:\+|00)?\(?\d{1,4}\)?[\s.\-]?\d{3,}[\s.\-]?\d{3,}'
    r'|\(\d{2,4}\)\s?\d{6,}'
)
_HANDLE_RE = re.compile(r'(?<!\w)@[a-z0-9_]{3,32}\b', re.IGNORECASE)
_DRUG_SALE_RE = re.compile(
    r'(?:'
    r'(?:\b(?:buy|buying|bought|sell|selling|sale|purchase|order|ordering)\b'
    r'.{0,48}'
    r'\b(?:marijuana|cannabis|weed|ketamine|cocaine|mdma|meth|heroin|hashish|ganja)\b)'
    r'|'
    r'(?:\b(?:marijuana|cannabis|weed|ketamine|cocaine|mdma|meth|heroin|hashish|ganja)\b'
    r'.{0,48}'
    r'\b(?:buy|buying|bought|sell|selling|sale|purchase|order|ordering)\b)'
    r')',
    re.IGNORECASE | re.DOTALL,
)
_CAMPAIGN_RE = re.compile(
    r'asian\s*therapist|uae\s*therapist|silk\s*road|addsilkroad|zetherapist|'
    r'\*[a-z]{2,12}therapist\*|legit[_\s]?deliver|top\s*shelf|'
    r'crypto(?:currency)?\s*smuggl',
    re.IGNORECASE,
)
# Long glued tokens used to evade keyword filters. Civic compounds exist
# (especially in German), so this only scores when several appear or when
# they sit next to a contact channel.
_MASHED_TOKEN_RE = re.compile(r'\b[A-Za-z][A-Za-z\'*]{21,}\b')
_URL_LIKE_RE = re.compile(r'https?://|www\.', re.IGNORECASE)
_CRYPTO_BANK_RE = re.compile(
    r'\b(?:crypto(?:currency)?|bitcoin|btc|wallet|bank\s*account)\b',
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ContentSpamVerdict:
    blocked: bool
    score: int
    reasons: tuple[str, ...] = field(default_factory=tuple)
    threshold: int = DEFAULT_SCORE_THRESHOLD


def _threshold() -> int:
    try:
        configured = current_app.config.get('CONTENT_SPAM_SCORE_THRESHOLD')
    except RuntimeError:
        configured = None
    if configured is None:
        return DEFAULT_SCORE_THRESHOLD
    try:
        return max(1, int(configured))
    except (TypeError, ValueError):
        return DEFAULT_SCORE_THRESHOLD


def assess_user_content_spam(text: str | None) -> ContentSpamVerdict:
    """Return a scored verdict for user-authored statement/response text."""
    raw = (text or '').strip()
    if not raw:
        return ContentSpamVerdict(blocked=False, score=0, reasons=())

    score = 0
    reasons: list[str] = []
    channels = len(_CONTACT_CHANNEL_RE.findall(raw))
    phones = len(_PHONE_RE.findall(raw))
    handles = len(_HANDLE_RE.findall(raw))
    mashed = [
        token for token in _MASHED_TOKEN_RE.findall(raw)
        if not _URL_LIKE_RE.search(token)
    ]

    if channels and phones:
        score += 4
        reasons.append('contact_channel_with_phone')
    if channels and handles:
        score += 3
        reasons.append('contact_channel_with_handle')
    if channels >= 2:
        score += 2
        reasons.append('multiple_contact_channels')

    if _DRUG_SALE_RE.search(raw):
        score += 4
        reasons.append('drug_marketplace')

    if _CAMPAIGN_RE.search(raw):
        score += 5
        reasons.append('known_spam_campaign')

    if len(mashed) >= 3:
        score += 3
        reasons.append('mashed_word_density')
    elif mashed and channels:
        score += 2
        reasons.append('mashed_word_with_contact')

    if _CRYPTO_BANK_RE.search(raw) and (channels or phones or handles):
        score += 3
        reasons.append('crypto_or_bank_with_contact')

    threshold = _threshold()
    return ContentSpamVerdict(
        blocked=score >= threshold,
        score=score,
        reasons=tuple(reasons),
        threshold=threshold,
    )


def is_unsolicited_spam(text: str | None) -> bool:
    return assess_user_content_spam(text).blocked
