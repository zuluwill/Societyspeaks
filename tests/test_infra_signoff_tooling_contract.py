from pathlib import Path
import json
import subprocess


ROOT = Path(__file__).resolve().parents[1]


def test_connection_budget_tooling_files_exist():
    assert (ROOT / "scripts/calc_connection_budget.py").exists()
    assert (ROOT / "docs/NSP_CONNECTION_BUDGET.md").exists()
    assert (ROOT / "docs/NSP_INFRA_SIGNOFF_TEMPLATE.md").exists()


def test_connection_budget_script_outputs_expected_fields():
    result = subprocess.run(
        ["python3", "scripts/calc_connection_budget.py", "--web-workers", "4"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    assert "formula" in payload
    assert "computed" in payload
    assert "total_connections" in payload["computed"]
    assert "within_budget" in payload["computed"]
