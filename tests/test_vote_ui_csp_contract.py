from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
STATEMENT_CARD_TEMPLATE = REPO_ROOT / "app/templates/discussions/_statement_card.html"
NATIVE_VIEW_TEMPLATE = REPO_ROOT / "app/templates/discussions/view_native.html"
EMBED_VIEW_TEMPLATE = REPO_ROOT / "app/templates/discussions/embed_discussion.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_native_vote_buttons_do_not_use_inline_onclick_handlers():
    """Protect against CSP regressions that silently break voting clicks."""
    html = _read(STATEMENT_CARD_TEMPLATE)
    assert 'data-vote="1"' in html
    assert 'data-vote="-1"' in html
    assert 'data-vote="0"' in html
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
