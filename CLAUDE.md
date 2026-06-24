# CLAUDE.md — Society Speaks

Guidance for AI tools and developers working in this repository (Flask, Flask-Babel, Jinja2).

## Quick checks

- **Python:** use `python3`.
- **Tests:** `python3 -m pytest` (from repo root; target files or `-k` as needed).
- **Translations:** see `scripts/compile_translations.sh` for the full extract → update → compile workflow.

## i18n and HTML escaping

- **One logical `msgid` in templates:** keep strings like `Discussions & Programmes` with a literal `&` in the source. Do not duplicate msgids with `&amp;` in the Python/Jinja string just to please HTML; that desynchronizes `messages.pot` and all `.po` files.
- **Text nodes / attributes in HTML** where gettext may return **Markup** and the string can contain `&` or `<`: use the Jinja filter `|escape_i18n` so output is always entity-safe. Implementation: `app/lib/jinja_i18n.py` (`Markup(escape(str(value)))` unwraps Markup before escaping; the default `|e` does not in that situation).
- **Do not** apply `|escape_i18n` to copy that is intentionally HTML (`|safe`, rich entity markup from translators, etc.).
- **Email templates** that pass HTML fragments into `gettext`: use `email_anchor_html` from `app/email_utils.py` (registered as Jinja global) so `href` / attributes are escaped and link bodies are `Markup` where needed. See existing email templates for patterns.
- **babel:** `babel.cfg` documents where to look for `escape_i18n` when editing templates.

## SEO (canonical, robots, sitemap)

- **Canonical:** indexable templates must set `{% block canonical %}{{ url_for(..., _external=True) }}{% endblock %}` — never rely on `request.base_url` for public content. `og:url` defaults to `self.canonical()` in `layout.html`.
- **hreflang:** emitted globally from `layout.html` (`{% block hreflang %}`) using the canonical URL + `?lang=`. Do not add per-page hreflang tags.
- **robots:** use `{% block meta_robots %}` only — never `<meta name="robots">` inside `{% block extra_head %}` (duplicates layout). Utility, admin, auth, errors, filtered search, and game sessions are `noindex`; marketing hubs stay `index, follow`.
- **URL aliases:** `/daily`, `/brief`, `/brief/today`, `/brief/weekly` 301 to dated permalinks. Sitemap lists stable URLs only (no aliases, game sessions, or quick-run paths).
- **Statements:** canonical points at the parent discussion, not the statement URL.
- **Tests:** `tests/test_marketing_seo_render.py` and `tests/test_sitemap.py` guard regressions — run when touching templates or `app/seo.py`.
- **List pages:** hub URL is indexable; paginated or filtered variants (`?page=`, `?q=`, `?type=`, etc.) use `seo_noindex` + canonical to the hub (same pattern as search).
- **Social (OG/Twitter):** indexable templates with `{% block canonical %}` must also set `og_title`, `og_description`, `twitter_title`, and `twitter_description` — never rely on layout defaults on public pages.
- **GEO:** keep `app/static/llms.txt` aligned with canonical URL patterns (dated permalinks, not redirect aliases). Linked from `robots.txt` as `LLMsTXT`. Site-wide `meta name="ai-model-context"` lives in `layout.html`.

## Participation & vote semantics

- **Published vs audit:** Participant-facing counts and aligned aggregates exclude votes on deleted or negatively moderated statements (`visible_statement_vote_filters` in `app/lib/participation_metrics.py`). Raw `statement_vote` rows may still exist for audit; do not mix definitions without labelling the export or UI. Full rationale: [adr/0001-published-vs-audit-vote-semantics.md](./adr/0001-published-vs-audit-vote-semantics.md).
- **Anonymous voters:** Use `anonymous_fingerprint_aliases_for_daily_lookup()` from `app/lib/vote_identity.py` for “this visitor’s votes” lookups (legacy cookies + embed fingerprint). Avoid `session_fingerprint == single_fp` for UX summaries unless you document why.

## Scope

Project overview, setup, and feature list live in [README.md](./README.md). Keep this file limited to conventions that are easy to miss in code review.
