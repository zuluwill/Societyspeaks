"""
Locale resolution for Flask-Babel and content translation.

Single source of truth for language detection — used by both Flask-Babel's locale
selector (for UI strings) and the content translation service (for dynamic text).

Priority order:
  1. Authenticated user's saved language preference (DB)
  2. ?lang= query parameter (in-page selector)
  3. ss_lang cookie (remembered from previous visit)
  4. Accept-Language header (browser locale negotiation)
  5. 'en' fallback
"""
import logging

logger = logging.getLogger(__name__)

# Canonical set of supported languages. Imported by translation.py to avoid duplication.
SUPPORTED_LANGUAGES: dict[str, dict] = {
    'en': {'name': 'English',              'native': 'English',    'dir': 'ltr'},
    'es': {'name': 'Spanish',              'native': 'Español',    'dir': 'ltr'},
    'nl': {'name': 'Dutch',                'native': 'Nederlands', 'dir': 'ltr'},
    'zh': {'name': 'Chinese (Simplified)', 'native': '中文',        'dir': 'ltr'},
    'de': {'name': 'German',               'native': 'Deutsch',    'dir': 'ltr'},
    'fr': {'name': 'French',               'native': 'Français',   'dir': 'ltr'},
    'ja': {'name': 'Japanese',             'native': '日本語',       'dir': 'ltr'},
    'pt': {'name': 'Portuguese',           'native': 'Português',  'dir': 'ltr'},
    'ar': {'name': 'Arabic',               'native': 'العربية',    'dir': 'rtl'},
    'hi': {'name': 'Hindi',                'native': 'हिन्दी',       'dir': 'ltr'},
    'ko': {'name': 'Korean',               'native': '한국어',       'dir': 'ltr'},
}


def resolve_locale() -> str:
    """
    Flask-Babel locale selector. Called once per request by Babel to determine
    which .po file to use for `_()` / `gettext()` calls.

    Also used directly by the content translation service so both UI strings
    and dynamic content use exactly the same language resolution logic.
    """
    from flask import request
    from flask_login import current_user

    # 1. Authenticated user's saved preference
    try:
        if current_user.is_authenticated and getattr(current_user, 'language', None):
            lang = current_user.language
            if lang in SUPPORTED_LANGUAGES:
                return lang
    except Exception:
        pass

    # 2. Explicit query parameter (?lang=fr)
    try:
        lang = request.args.get('lang', '').strip().lower()[:10]
        if lang in SUPPORTED_LANGUAGES:
            return lang
    except Exception:
        pass

    # 3. Cookie set by language selector or embed route
    try:
        lang = request.cookies.get('ss_lang', '').strip().lower()[:10]
        if lang in SUPPORTED_LANGUAGES:
            return lang
    except Exception:
        pass

    # 4. Browser Accept-Language negotiation via Werkzeug
    try:
        accepted = request.accept_languages.best_match(list(SUPPORTED_LANGUAGES.keys()))
        if accepted:
            return accepted
    except Exception:
        pass

    return 'en'


def email_html_locale_kwargs(locale_code: str | None) -> dict[str, str]:
    """
    ``lang`` and ``dir`` attributes for transactional HTML emails (``base_email``).

    Matches the active Flask-Babel language code (e.g. ``en``, ``zh``, ``ar``) to
    BCP‑47-ish primary language tags and to ``dir`` from :data:`SUPPORTED_LANGUAGES`
    so RTL layouts (Arabic) render correctly across clients.

    Intended for merging into ``render_template`` contexts next to ``force_locale``.
    """
    from babel import Locale as BabelLocale

    raw = (locale_code or 'en').strip() or 'en'
    raw = raw.replace('-', '_')
    try:
        lc = BabelLocale.parse(raw, sep='_')
        lang_key = lc.language or 'en'
    except Exception:
        lang_key = 'en'

    meta = SUPPORTED_LANGUAGES.get(lang_key) or {}
    return {'html_lang': lang_key, 'html_dir': meta.get('dir', 'ltr')}


def resolve_user_locale(user=None) -> str:
    """
    Resolve the locale to use when rendering for a specific user *outside* a
    request context — e.g. email sends, background jobs, scheduled digests.

    Uses user.language if present + supported, else falls back to 'en'.
    Never touches request / cookies (those don't exist in these contexts).
    """
    if user is None:
        return 'en'
    lang = getattr(user, 'language', None)
    if lang and lang in SUPPORTED_LANGUAGES:
        return lang
    return 'en'


def language_preference_cookie_params():
    """
    Keyword arguments for Flask Response.set_cookie('ss_lang', ...).

    Aligns with SESSION_COOKIE_SECURE in production (HTTPS-only cookie) while
    keeping SameSite=Lax for normal navigation flows.
    """
    from flask import current_app

    kw = {
        'max_age': 365 * 24 * 3600,
        'samesite': 'Lax',
        'path': '/',
    }
    if current_app.config.get('SESSION_COOKIE_SECURE'):
        kw['secure'] = True
    return kw
