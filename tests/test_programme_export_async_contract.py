from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_programme_export_job_model_exists():
    source = _read("app/models.py")
    assert "class ProgrammeExportJob" in source
    assert "STATUS_QUEUED = 'queued'" in source
    assert "STATUS_RUNNING = 'running'" in source
    assert "STATUS_COMPLETED = 'completed'" in source


def test_programme_export_route_enqueues_instead_of_streaming():
    source = _read("app/programmes/routes.py")
    assert "enqueue_programme_export_job(" in source
    assert "stream_programme_export_csv(" not in source
    assert "stream_programme_export_json(" not in source


def test_signed_download_token_helpers_present():
    source = _read("app/programmes/export_jobs.py")
    assert "generate_export_download_token(" in source
    assert "verify_export_download_token(" in source


def test_worker_processes_programme_export_queue():
    source = _read("scripts/run_consensus_worker.py")
    assert "process_next_programme_export_job" in source
    assert "mark_stale_programme_export_jobs" in source
