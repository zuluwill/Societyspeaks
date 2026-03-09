from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_launch_room_health_route_exists():
    source = _read("app/admin/routes.py")
    assert "@admin_bp.route('/launch-room/health.json')" in source
    assert "def launch_room_health():" in source
    assert "get_consensus_queue_metrics" in source
    assert "get_programme_export_queue_metrics" in source


def test_slo_and_gate_docs_exist():
    assert (ROOT / "docs/NSP_SLO_ALERT_POLICY.md").exists()
    assert (ROOT / "docs/NSP_GO_NO_GO_GATES.md").exists()


def test_checklist_references_launch_room_and_slo_docs():
    source = _read("docs/NSP_2M_READINESS_CHECKLIST.md")
    assert "NSP_SLO_ALERT_POLICY.md" in source
    assert "/admin/launch-room/health.json" in source
    assert "NSP_GO_NO_GO_GATES.md" in source
