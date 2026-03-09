from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_consensus_trigger_enqueues_job_instead_of_running_inline():
    source = _read("app/discussions/consensus.py")
    assert "enqueue_consensus_job(" in source
    assert "run_consensus_analysis(" not in source


def test_consensus_job_model_has_lifecycle_statuses():
    source = _read("app/models.py")
    assert "class ConsensusJob" in source
    assert "STATUS_QUEUED = 'queued'" in source
    assert "STATUS_RUNNING = 'running'" in source
    assert "STATUS_COMPLETED = 'completed'" in source
    assert "STATUS_FAILED = 'failed'" in source
    assert "STATUS_STALE = 'stale'" in source
    assert "STATUS_DEAD_LETTER = 'dead_letter'" in source


def test_scheduler_processes_queue():
    source = _read("app/scheduler.py")
    assert "process_consensus_job_queue" in source
    assert "process_next_consensus_job" in source


def test_scheduler_queue_processing_guarded_by_feature_flag():
    """
    process_consensus_job_queue must no-op unless CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER
    is enabled.  This prevents heavy sklearn clustering from running in the scheduler
    thread when a dedicated worker process is deployed instead.
    """
    source = _read("app/scheduler.py")
    assert "CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER" in source
    # Guard must appear before the call in the scheduler function.
    guard_pos = source.index("CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER")
    call_pos = source.index("process_next_consensus_job")
    assert guard_pos < call_pos, (
        "CONSENSUS_QUEUE_PROCESS_IN_SCHEDULER guard must appear before "
        "process_next_consensus_job() call in scheduler.py"
    )


def test_worker_script_sets_disable_scheduler_before_import():
    """
    run_consensus_worker.py must set DISABLE_SCHEDULER before importing the
    Flask app, otherwise the in-app scheduler starts inside the worker process.
    """
    source = _read("scripts/run_consensus_worker.py")
    disable_pos = source.index("DISABLE_SCHEDULER")
    import_pos = source.index("from app import create_app")
    assert disable_pos < import_pos, (
        "DISABLE_SCHEDULER must be set before 'from app import create_app' "
        "in run_consensus_worker.py — ordering matters for env injection."
    )
    worker_env_pos = source.index("CONSENSUS_WORKER_PROCESS")
    assert worker_env_pos < import_pos, (
        "CONSENSUS_WORKER_PROCESS must be set before app imports in worker entrypoint."
    )


def test_worker_script_has_heartbeat_key():
    """Worker must publish a Redis heartbeat so health monitors can detect worker death."""
    source = _read("scripts/run_consensus_worker.py")
    assert "consensus_worker:last_heartbeat_at" in source
    assert "consensus_worker:heartbeat:" in source


def test_replit_workflow_includes_worker_pool_topology():
    source = _read(".replit")
    assert "Consensus Worker Pool (x3)" in source
    assert "Project (Worker Pool x3)" in source


def test_get_consensus_queue_metrics_exists():
    """get_consensus_queue_metrics() must exist for health telemetry."""
    source = _read("app/discussions/jobs.py")
    assert "def get_consensus_queue_metrics(" in source
    assert "queue_lag_seconds" in source


def test_consensus_execution_is_worker_only_by_default():
    source = _read("app/discussions/jobs.py")
    assert "CONSENSUS_WORKER_PROCESS" in source
    assert "CONSENSUS_ALLOW_IN_PROCESS_EXECUTION" in source
