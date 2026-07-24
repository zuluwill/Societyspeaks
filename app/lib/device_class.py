"""Coarse device buckets from HTTP User-Agent for server-side funnel analytics."""

from __future__ import annotations

import re
from typing import Literal, Optional

DeviceClass = Literal['mobile', 'tablet', 'desktop', 'bot', 'unknown']

_MOBILE_RE = re.compile(
    r'iphone|ipod|(?:android.*mobile)|windows phone|mobile safari|blackberry',
    re.I,
)
_TABLET_RE = re.compile(r'ipad|tablet|(?:android(?!.*mobile))', re.I)


def classify_user_agent(
    user_agent: Optional[str],
    *,
    treat_bot: bool = True,
) -> DeviceClass:
    """Map a User-Agent string to a stable analytics bucket."""
    if not user_agent or not str(user_agent).strip():
        return 'unknown'
    if treat_bot:
        from app.lib.session_policy import SESSION_SKIP_UA_INDICATORS, user_agent_is_bot

        if user_agent_is_bot(user_agent, SESSION_SKIP_UA_INDICATORS):
            return 'bot'
    if _MOBILE_RE.search(user_agent):
        return 'mobile'
    if _TABLET_RE.search(user_agent):
        return 'tablet'
    return 'desktop'


def device_class_from_request() -> DeviceClass:
    """Return the device bucket for the current Flask request, if any."""
    from app.lib.posthog_utils import _get_request_user_agent

    return classify_user_agent(_get_request_user_agent())
