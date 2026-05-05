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

## Participation & vote semantics

- **Published vs audit:** Participant-facing counts and aligned aggregates exclude votes on deleted or negatively moderated statements (`visible_statement_vote_filters` in `app/lib/participation_metrics.py`). Raw `statement_vote` rows may still exist for audit; do not mix definitions without labelling the export or UI. Full rationale: [adr/0001-published-vs-audit-vote-semantics.md](./adr/0001-published-vs-audit-vote-semantics.md).
- **Anonymous voters:** Use `anonymous_fingerprint_aliases_for_daily_lookup()` from `app/lib/vote_identity.py` for “this visitor’s votes” lookups (legacy cookies + embed fingerprint). Avoid `session_fingerprint == single_fp` for UX summaries unless you document why.

## Scope

Project overview, setup, and feature list live in [README.md](./README.md). Keep this file limited to conventions that are easy to miss in code review.
