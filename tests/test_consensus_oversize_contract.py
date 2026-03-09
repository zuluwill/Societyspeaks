from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_consensus_engine_has_execution_plan_and_oversize_fallback():
    source = _read("app/lib/consensus_engine.py")
    assert "def get_consensus_execution_plan(" in source
    assert "'mode': 'sampled_incremental'" in source
    assert "MAX_CONSENSUS_FULL_MATRIX_STATEMENTS" in source
    assert "def build_oversize_consensus_results(" in source
    assert "'method': 'sampled_incremental_aggregate'" in source


def test_consensus_routes_use_execution_plan_for_queueing():
    source = _read("app/discussions/consensus.py")
    assert "get_consensus_execution_plan" in source
    assert "analysis_mode" in source


def test_jobs_use_execution_plan_not_only_can_cluster():
    source = _read("app/discussions/jobs.py")
    assert "get_consensus_execution_plan" in source
    assert "plan['is_ready']" in source
