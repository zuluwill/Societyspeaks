from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_k6_suite_files_exist():
    assert (ROOT / "load-tests/k6/vote_storm.js").exists()
    assert (ROOT / "load-tests/k6/read_storm.js").exists()
    assert (ROOT / "load-tests/k6/export_burst.js").exists()
    assert (ROOT / "load-tests/k6/partner_lookup_burst.js").exists()
    assert (ROOT / "load-tests/k6/nsp_uk_traffic_profile.js").exists()
    assert (ROOT / "load-tests/k6/queue_backlog_spike.js").exists()


def test_k6_scripts_define_options():
    for path in [
        "load-tests/k6/vote_storm.js",
        "load-tests/k6/read_storm.js",
        "load-tests/k6/export_burst.js",
        "load-tests/k6/partner_lookup_burst.js",
        "load-tests/k6/nsp_uk_traffic_profile.js",
        "load-tests/k6/queue_backlog_spike.js",
    ]:
        source = _read(path)
        assert "export const options =" in source


def test_load_test_readme_mentions_phase_61_scenarios():
    source = _read("load-tests/README.md")
    assert "Vote storm" in source
    assert "Read storm" in source
    assert "Export burst" in source
    assert "Partner lookup burst" in source
    assert "UK mixed traffic profile" in source
    assert "Queue backlog spike" in source
    assert "redis_failover.md" in source
    assert "worker_crash_recovery.md" in source
