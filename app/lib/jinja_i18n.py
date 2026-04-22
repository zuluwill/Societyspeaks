"""Jinja filters for i18n-safe HTML output (Flask-Babel and Markup)."""

from markupsafe import Markup, escape


def escape_i18n(value):
    """
    HTML-escape translated text for normal HTML text/attribute content, even when
    Flask-Babel gettext returns ``Markup`` (Jinja2 newstyle i18n: the default
    ``|e`` filter may not re-escape Markup, producing a bare ``&`` in the response).

    Use when the logical msgid can contain an ampersand, e.g.
    ``{{ _('Discussions & Programmes')|escape_i18n }}`` so the string stays one
    msgid in ``.po`` files and the HTML contains ``&amp;`` where required.

    Do not use for strings that intentionally include HTML (``|safe`` rich copy,
    ``&ndash;``-style msgids, etc.); those already control escaping via ``|safe``.
    """
    if value is None:
        return Markup()
    return Markup(escape(str(value)))
