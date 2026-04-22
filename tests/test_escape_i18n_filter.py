"""Tests for the escape_i18n Jinja filter (gettext + Markup + HTML entity output)."""
from markupsafe import Markup


def test_escape_i18n_escapes_markup_like_plain_str(app):
    t = app.jinja_env.from_string("{{ m|escape_i18n }}")
    assert t.render(m=Markup("Discussions & Programmes")) == "Discussions &amp; Programmes"


def test_escape_i18n_handles_none(app):
    t = app.jinja_env.from_string("{{ m|escape_i18n }}")
    assert t.render(m=None) == ""


def test_escape_i18n_module_escapes_str_and_markup():
    """Unit test for :func:`app.lib.jinja_i18n.escape_i18n` (no Jinja indirection)."""
    from app.lib.jinja_i18n import escape_i18n

    assert str(escape_i18n("Discussions & Programmes")) == "Discussions &amp; Programmes"
    assert str(escape_i18n(Markup("Discussions & Programmes"))) == "Discussions &amp; Programmes"
    assert str(escape_i18n(None)) == ""


def test_escape_i18n_module_escapes_angle_brackets_in_plain_str():
    """Non-Markup text with ``<`` must become entities (e.g. comparison or stray markup)."""
    from app.lib.jinja_i18n import escape_i18n

    assert str(escape_i18n("a < b")) == "a &lt; b"
    assert str(escape_i18n("x > y")) == "x &gt; y"


def test_escape_i18n_jinja_plain_str_ampersand_and_lt(app):
    """Jinja path with a plain :class:`str` (not Markup) for ``&`` and ``<``."""
    t = app.jinja_env.from_string("{{ s|escape_i18n }}")
    assert t.render(s="Left & Centre") == "Left &amp; Centre"
    assert t.render(s="a < b") == "a &lt; b"
