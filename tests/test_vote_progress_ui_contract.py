from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATEMENTS_PATH = ROOT / "app" / "discussions" / "statements.py"
NATIVE_TEMPLATE_PATH = ROOT / "app" / "templates" / "discussions" / "view_native.html"
ROUTES_PATH = ROOT / "app" / "discussions" / "routes.py"
CONSENSUS_PATH = ROOT / "app" / "discussions" / "consensus.py"


def test_vote_response_exposes_consensus_progress_fields():
    source = STATEMENTS_PATH.read_text(encoding="utf-8")
    assert "'user_vote_count':" in source
    assert "'participation_threshold':" in source
    assert "'is_consensus_unlocked':" in source
    assert "'consensus_progress':" in source


def test_native_template_contains_live_progress_hooks():
    source = NATIVE_TEMPLATE_PATH.read_text(encoding="utf-8")
    assert "[data-statement-id][data-quick-response-url]" in source
    assert 'id="consensus-analysis-link"' in source
    assert 'id="analysis-vote-progress"' in source
    assert 'id="consensus-participants-count"' in source
    assert 'id="consensus-total-votes-count"' in source
    assert "updateConsensusUiFromServer(data)" in source
    assert "consensus-progress-card" in source
    assert "classList.toggle('hidden', isReady)" in source


def test_view_discussion_provides_computed_participant_count():
    source = ROUTES_PATH.read_text(encoding="utf-8")
    assert "discussion_participant_count" in source
    assert "build_consensus_ui_state(" in source
    assert "if discussion.has_native_statements:" in source


def test_consensus_helper_exposes_shared_ui_payload():
    source = CONSENSUS_PATH.read_text(encoding="utf-8")
    assert "def build_consensus_ui_state(discussion, precomputed_metrics=None, participant_count=None):" in source
    assert "'user_vote_count':" in source
    assert "'participation_threshold':" in source
    assert "'is_consensus_unlocked':" in source
    assert "'consensus_progress':" in source
