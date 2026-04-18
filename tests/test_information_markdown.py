"""Sanitised Markdown for discussion information steps (journey optional reading)."""

import pytest

from app.programmes import utils


pytest.importorskip("markdown")
pytest.importorskip("bleach")
pytest.importorskip("bs4")


def test_render_safe_markdown_adds_target_blank_and_rel_on_http_links():
    html = utils.render_safe_markdown("[IPCC](https://www.ipcc.ch/report)")
    assert 'href="https://www.ipcc.ch/report"' in html
    assert 'target="_blank"' in html
    assert "noopener" in html
    assert "noreferrer" in html


def test_render_safe_markdown_mailto_unchanged_no_target_blank():
    html = utils.render_safe_markdown("[Contact](mailto:hello@example.com)")
    assert "mailto:hello@example.com" in html
    assert "target=" not in html
