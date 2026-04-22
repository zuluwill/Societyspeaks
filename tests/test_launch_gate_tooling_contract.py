from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_launch_gate_tooling_files_exist():
    if not (ROOT / "docs").exists():
        pytest.skip("docs/ not present (gitignored internal planning)")
    assert (ROOT / "scripts/collect_launch_evidence.py").exists()
    assert (ROOT / "docs/NSP_GATE_EXECUTION_RUNBOOK.md").exists()


def test_collect_launch_evidence_includes_launch_room_endpoint():
    source = _read("scripts/collect_launch_evidence.py")
    assert "/admin/launch-room/health.json" in source
    assert "gate_report.md" in source


def test_checklist_references_gate_execution_toolkit():
    if not (ROOT / "docs").exists():
        pytest.skip("docs/ not present (gitignored internal planning)")
    source = _read("docs/NSP_2M_READINESS_CHECKLIST.md")
    assert "NSP_GATE_EXECUTION_RUNBOOK.md" in source
    assert "collect_launch_evidence.py" in source
