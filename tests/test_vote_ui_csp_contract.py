from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATEMENT_CARD_TEMPLATE = REPO_ROOT / "app/templates/discussions/_statement_card.html"
STATEMENT_VIEW_TEMPLATE = REPO_ROOT / "app/templates/discussions/view_statement.html"
VOTE_BUTTONS_MACRO = REPO_ROOT / "app/templates/components/vote_buttons.html"
NATIVE_VIEW_TEMPLATE = REPO_ROOT / "app/templates/discussions/view_native.html"
EMBED_VIEW_TEMPLATE = REPO_ROOT / "app/templates/discussions/embed_discussion.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_native_vote_buttons_do_not_use_inline_onclick_handlers():
    """Protect against CSP regressions that silently break voting clicks."""
    card_html = _read(STATEMENT_CARD_TEMPLATE)
    macro_html = _read(VOTE_BUTTONS_MACRO)
    assert "vote_buttons" in card_html
    # Macro emits numeric vote values via Jinja (source is data-vote="{{ opt.value }}")
    assert 'data-vote="{{ opt.value }}"' in macro_html
    assert "'value': '1'" in macro_html
    assert "'value': '-1'" in macro_html
    assert "'value': '0'" in macro_html
    assert "onclick=" not in card_html
    assert "onclick=" not in macro_html
    assert "vote_buttons_form_post" in macro_html
    assert "statement_vote_stats_footer" in macro_html
    assert "<fieldset" in macro_html
    assert "sr-only" in macro_html


def test_statement_detail_page_uses_shared_vote_macros():
    html = _read(STATEMENT_VIEW_TEMPLATE)
    macro_html = _read(VOTE_BUTTONS_MACRO)
    assert "vote_buttons_form_post" in html
    assert "statement_vote_stats_footer" in html
    assert "vote-btn-agree" in macro_html
    assert "vote-buttons-grid--form" in macro_html
    assert 'name="vote"' in macro_html
    assert "onclick=" not in html


def test_native_discussion_template_keeps_delegated_vote_click_handler():
    """Enforce delegated vote handling when unsafe-inline is disabled in CSP."""
    html = _read(NATIVE_VIEW_TEMPLATE)
    assert "document.addEventListener('click'" in html
    assert "const btn = e.target.closest('.vote-btn');" in html
    assert "voteOnStatement(statementId, voteValue);" in html
    assert "onclick=" not in html


def test_embed_template_keeps_non_inline_vote_binding():
    """Embed voting also relies on delegated handlers instead of inline onclick."""
    html = _read(EMBED_VIEW_TEMPLATE)
    assert "document.addEventListener('click'" in html
    assert "const voteBtn = e.target.closest('.vote-btn');" in html
    assert "vote(statementId, voteValue, voteBtn);" in html
    assert 'onclick="vote(' not in html
    assert "data-vote-selected" in html
    assert "vote-breakdown__hint" in html
