from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_vote_counter_deltas_are_applied_in_sql():
    source = _read("app/discussions/statements.py")
    assert "vote_count_agree    = GREATEST(0, vote_count_agree    + :agree_delta)" in source
    assert "vote_count_disagree = GREATEST(0, vote_count_disagree + :disagree_delta)" in source
    assert "vote_count_unsure   = GREATEST(0, vote_count_unsure   + :unsure_delta)" in source


def test_counter_integrity_helpers_exist():
    source = _read("app/discussions/counter_integrity.py")
    assert "def get_statement_counter_drift_metrics(" in source
    assert "def reconcile_statement_vote_counters(" in source
    assert "total_abs_drift" in source


def test_scheduler_runs_periodic_counter_reconciliation():
    source = _read("app/scheduler.py")
    assert "id='statement_counter_reconciliation'" in source
    assert "reconcile_statement_vote_counters" in source
    assert "COUNTER_DRIFT_ALERT_THRESHOLD" in source
