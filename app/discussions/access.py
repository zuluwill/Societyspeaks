"""Who may reach a discussion.

Every route that serves a discussion, its statements, its votes or its analysis
asks here, so each rule is written once:

* **Programme visibility**: a discussion in a programme follows the programme.
* **Sandbox**: a discussion created with a partner's test API key belongs to
  that partner's sandbox. It never appears on the public site. Its analysis is
  reachable by the owning partner, a site admin, or someone holding the sandbox
  link. The embed may read and write votes only with a short-lived token minted
  when that embed page was actually served.
* **Embed parents**: a partner-owned discussion can be framed and written to
  only from that partner's verified domains.
* **Link-only**: a self-serve consultation's discussion. Every shared route
  answers 404 for it. Participants and the host reach it only through the
  consultation routes (``app/consultations``), which do their own checks.
"""
from typing import List, Optional

from flask import abort, current_app, jsonify, request, session
from flask_login import current_user
from itsdangerous import BadSignature, SignatureExpired, URLSafeSerializer, URLSafeTimedSerializer

from app.programmes.permissions import can_view_programme

SANDBOX_KEY_PARAM = 'sandbox_key'
SANDBOX_EMBED_TOKEN_HEADER = 'X-Sandbox-Embed-Token'
_SANDBOX_KEY_SALT = 'sandbox-discussion-link'
_SANDBOX_EMBED_TOKEN_SALT = 'sandbox-embed-token'
_SANDBOX_EMBED_TOKEN_MAX_AGE = 7 * 24 * 3600
_SANDBOX_SESSION_KEY = 'sandbox_discussion_ids'
_SANDBOX_SESSION_LIMIT = 50


def is_sandbox_discussion(discussion) -> bool:
    """True for a discussion created with a partner's test API key."""
    return getattr(discussion, 'partner_env', None) == 'test'


def can_view_discussion(discussion, user=None) -> bool:
    """Programme visibility. A discussion outside a programme is public."""
    user = current_user if user is None else user
    programme = discussion.programme
    return programme is None or can_view_programme(programme, user)


def can_view_discussion_on_site(discussion, user=None) -> bool:
    """Public-site pages and listings: never a sandbox or link-only discussion."""
    return discussion.is_publicly_listable and can_view_discussion(discussion, user)


# ── Partner ownership and embed parents ─────────────────────────────────────

def owning_partner_id(discussion) -> Optional[int]:
    """``Partner.id`` of the partner that owns this discussion, if any.

    Older rows carry only the partner slug; a slug with no Partner account
    (legacy config-key partners) resolves to None.
    """
    if discussion.partner_fk_id is not None:
        return discussion.partner_fk_id
    slug = (discussion.partner_id or '').strip()
    if not slug:
        return None
    from app.models import Partner
    partner = Partner.query.filter_by(slug=slug).first()
    return partner.id if partner else None


def is_partner_scoped(discussion) -> bool:
    """Partner-owned or sandbox: the embed is locked to partner domains."""
    return (
        discussion.partner_fk_id is not None
        or bool((discussion.partner_id or '').strip())
        or is_sandbox_discussion(discussion)
    )


def allowed_embed_origins(discussion) -> List[str]:
    """Origins that may frame this discussion's embed.

    A partner-owned discussion is limited to its own partner's verified
    domains. A public discussion may be embedded by any verified partner.
    """
    from app.api.utils import get_partner_allowed_origins
    return get_partner_allowed_origins(
        env=discussion.partner_env,
        partner_id=owning_partner_id(discussion),
    )


def is_allowed_embed_origin(discussion, origin) -> bool:
    return bool(origin) and origin in allowed_embed_origins(discussion)


def embed_parent_denied(discussion) -> bool:
    """True when the embed must refuse the page that is framing it.

    Public discussions are embeddable anywhere. Partner-scoped ones check the
    parent (Origin, else Referer) against the allowlist when it is known;
    sandbox embeds in production, and live ones when
    ``PARTNER_EMBED_REQUIRE_PARENT_ORIGIN`` is set, also refuse an unknown parent.
    """
    if not is_partner_scoped(discussion):
        return False
    from app.api.utils import get_effective_embed_parent_origin
    parent = get_effective_embed_parent_origin()
    if parent:
        return not is_allowed_embed_origin(discussion, parent)
    in_production = (
        current_app.config.get('ENV') == 'production' and not current_app.testing
    )
    if not in_production:
        return False
    return is_sandbox_discussion(discussion) or bool(
        current_app.config.get('PARTNER_EMBED_REQUIRE_PARENT_ORIGIN')
    )


def embed_write_denial(discussion) -> Optional[str]:
    """Error code when an embed write must be refused, else None.

    Writes come from our own embed page (first-party origin) or, for server
    integrations, from the owning partner's domain.
    """
    if not is_partner_scoped(discussion):
        return None
    from app.api.utils import get_effective_embed_parent_origin, origin_matches_app_base_url
    origin = get_effective_embed_parent_origin()
    if not origin:
        return 'origin_required'
    if origin_matches_app_base_url(origin) or is_allowed_embed_origin(discussion, origin):
        return None
    return 'origin_not_allowed'


# ── Sandbox access ──────────────────────────────────────────────────────────

def _sandbox_serializer() -> URLSafeSerializer:
    return URLSafeSerializer(current_app.config['SECRET_KEY'], salt=_SANDBOX_KEY_SALT)


def sandbox_key_for(discussion) -> str:
    """Signed, non-expiring key for one sandbox discussion.

    Carried on the links handed to the owning partner (API, portal, embed) so
    their testers can open the analysis without a portal login.
    """
    return _sandbox_serializer().dumps(int(discussion.id))


def _sandbox_key_is_valid(discussion, key) -> bool:
    if not key:
        return False
    try:
        return _sandbox_serializer().loads(key) == int(discussion.id)
    except (BadSignature, TypeError, ValueError):
        return False


def remember_sandbox_grant(discussion_id: int) -> None:
    """Remember that this browser may open one sandbox discussion.

    Set only after a valid sandbox link was presented. Serving the embed does
    not set it: an iframed page cannot rely on a cookie, so it carries
    ``sandbox_embed_token`` instead.
    """
    granted = [int(i) for i in session.get(_SANDBOX_SESSION_KEY, []) if i != discussion_id]
    granted.append(int(discussion_id))
    session[_SANDBOX_SESSION_KEY] = granted[-_SANDBOX_SESSION_LIMIT:]


def _sandbox_embed_serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config['SECRET_KEY'], salt=_SANDBOX_EMBED_TOKEN_SALT)


def sandbox_embed_token(discussion) -> str:
    """Short-lived capability for the embed page of one sandbox discussion.

    Minted only when that page is served. The embed sends it on its own vote
    and statement requests. It does not open the analysis, and it is not a
    cookie: an iframed page cannot rely on one.
    """
    return _sandbox_embed_serializer().dumps(int(discussion.id))


def sandbox_embed_token_is_valid(discussion) -> bool:
    token = request.headers.get(SANDBOX_EMBED_TOKEN_HEADER) or ''
    if not token:
        return False
    try:
        granted = _sandbox_embed_serializer().loads(token, max_age=_SANDBOX_EMBED_TOKEN_MAX_AGE)
    except (BadSignature, SignatureExpired, TypeError, ValueError):
        return False
    return granted == int(discussion.id)


def can_reach_sandbox_discussion(discussion, user=None, *, allow_embed_token=False) -> bool:
    """Admin, owning partner, a browser that opened an allowed link, or the embed token."""
    user = current_user if user is None else user
    if getattr(user, 'is_authenticated', False) and getattr(user, 'is_admin', False):
        return True

    partner_id = owning_partner_id(discussion)
    if partner_id is not None and session.get('partner_portal_id') == partner_id:
        return True

    if discussion.id in session.get(_SANDBOX_SESSION_KEY, []):
        return True
    if _sandbox_key_is_valid(discussion, request.args.get(SANDBOX_KEY_PARAM)):
        # Remembered so the page's own data requests and onward links work.
        remember_sandbox_grant(discussion.id)
        return True
    if allow_embed_token and sandbox_embed_token_is_valid(discussion):
        return True

    return False


# ── Route guards ────────────────────────────────────────────────────────────

def discussion_access_denial(discussion, user=None, *, allow_embed_token=False) -> Optional[int]:
    """HTTP status to refuse with, or None when the request may proceed.

    For routes that serve statements, votes and analysis. A sandbox discussion
    answers 404 to anyone outside it, so its existence is not disclosed.
    ``allow_embed_token`` is for the embed's own vote and statement routes.
    The analysis routes leave it off, so the embed token cannot open them.

    A link-only discussion answers 404 here always: it is served by the
    consultation routes instead.
    """
    if discussion.link_only:
        return 404
    if is_sandbox_discussion(discussion) and not can_reach_sandbox_discussion(
        discussion, user, allow_embed_token=allow_embed_token
    ):
        return 404
    if not can_view_discussion(discussion, user):
        return 403
    return None


def enforce_discussion_access(discussion, *, allow_embed_token=False) -> None:
    """Abort unless the current request may reach this discussion's data."""
    denial = discussion_access_denial(discussion, allow_embed_token=allow_embed_token)
    if denial:
        abort(denial)


def discussion_access_denial_json(discussion, *, allow_embed_token=False):
    """JSON refusal ``(response, status)`` for API routes, or None."""
    denial = discussion_access_denial(discussion, allow_embed_token=allow_embed_token)
    if denial == 404:
        return jsonify({'error': 'not_found'}), 404
    if denial:
        return jsonify({'error': 'forbidden'}), denial
    return None


def enforce_site_visibility(discussion) -> None:
    """404 unless this discussion may appear on the public site."""
    if not can_view_discussion_on_site(discussion):
        abort(404)
