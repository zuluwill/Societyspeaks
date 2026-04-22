"""Unit tests for app.email_utils helpers."""
from markupsafe import Markup

from app.email_utils import email_anchor_html


def test_email_anchor_html_returns_markup_with_escaped_href():
    out = email_anchor_html('https://ex.com/a?x=1&y=2', 'Label')
    assert isinstance(out, Markup)
    assert 'https://ex.com/a?x=1&amp;y=2' in str(out)
    assert "<a " in str(out)
    assert ">Label</a>" in str(out)


def test_email_anchor_html_escapes_quotes_in_inner_text():
    out = email_anchor_html("https://x", 'Say "hi"')
    assert "&#34;hi&#34;" in str(out)


def test_email_anchor_html_accepts_inner_markup_unmodified():
    inner = Markup("<em>OK</em>")
    out = email_anchor_html("https://x", inner)
    assert "<em>OK</em>" in str(out)
