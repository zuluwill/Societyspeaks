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


def test_worker_pool_runs_in_parallel_not_sequential():
    """
    Worker Pool (x3) must start workers in parallel.

    The workflow must either:
    (a) use Replit's native mode = "parallel" with 3 separate shell.exec tasks, OR
    (b) use a bash command with background (&) operators — NOT && which is sequential.

    The && operator would start worker-2 only when worker-1 exits, making the pool
    effectively single-worker under normal operation.
    """
    source = _read(".replit")
    # Find the Worker Pool *definition* block (name = "..."), not an args reference
    pool_start = source.index('name = "Consensus Worker Pool (x3)"')
    # Grab everything from the definition until the next workflow section or EOF
    next_workflow = source.find("\n[[workflows.workflow]]", pool_start + 1)
    pool_section = source[pool_start: next_workflow if next_workflow != -1 else len(source)]

    # If there are multiple tasks (native parallel), verify no && usage
    # If single task (bash wrapper), verify & parallel not && sequential
    if pool_section.count("shell.exec") >= 3:
        # Native 3-task parallel mode — sequential chaining forbidden
        assert "&&" not in pool_section, (
            "Worker pool tasks must not use && (sequential). Use separate tasks with mode=parallel."
        )
    else:
        # Single bash task — must use & background operators, not && sequential chaining
        assert "&&" not in pool_section, (
            "Worker pool bash command must not use && (sequential). "
            "Use & to background workers so all 3 start simultaneously."
        )
        # Must have at least 2 background operator & references for worker-2 and worker-3
        bg_count = pool_section.count(" & ")
        assert bg_count >= 2, (
            f"Worker pool bash command must background workers with &, found only {bg_count} & operators."
        )


def test_get_consensus_queue_metrics_exists():
    """get_consensus_queue_metrics() must exist for health telemetry."""
    source = _read("app/discussions/jobs.py")
    assert "def get_consensus_queue_metrics(" in source
    assert "queue_lag_seconds" in source


def test_consensus_execution_is_worker_only_by_default():
    source = _read("app/discussions/jobs.py")
    assert "CONSENSUS_WORKER_PROCESS" in source
    assert "CONSENSUS_ALLOW_IN_PROCESS_EXECUTION" in source


def test_app_role_bootstrap_translates_to_low_level_flags():
    """
    APP_ROLE must be resolved at the top of create_app() before any flag reads.
    The bootstrap must cover web, scheduler, and worker roles.
    """
    source = _read("app/__init__.py")
    assert "APP_ROLE" in source
    create_app_pos = source.index("def create_app()")
    role_pos = source.index("APP_ROLE", create_app_pos)
    scheduler_gate_pos = source.index("DISABLE_SCHEDULER", create_app_pos)
    assert role_pos < scheduler_gate_pos, (
        "APP_ROLE bootstrap must appear before DISABLE_SCHEDULER gate in create_app()"
    )
    # All three roles must be covered
    role_section = source[role_pos: role_pos + 700]
    assert "DISABLE_SCHEDULER" in role_section
    assert "REPLIT_DEPLOYMENT" in role_section
    assert "CONSENSUS_WORKER_PROCESS" in role_section


def test_run_scheduler_sets_app_role_before_import():
    """
    scripts/run_scheduler.py must set APP_ROLE=scheduler before importing the
    Flask app so create_app() receives the correct role at bootstrap time.
    """
    source = _read("scripts/run_scheduler.py")
    role_pos = source.index("APP_ROLE")
    import_pos = source.index("from app import create_app")
    assert role_pos < import_pos, (
        "APP_ROLE must be set before 'from app import create_app' in run_scheduler.py"
    )
    assert "scheduler" in source[role_pos: role_pos + 60], (
        "run_scheduler.py must set APP_ROLE to 'scheduler'"
    )


def test_run_scheduler_has_clean_shutdown():
    """Scheduler process must handle SIGTERM for clean shutdown."""
    source = _read("scripts/run_scheduler.py")
    assert "SIGTERM" in source
    assert "signal.signal" in source


def test_deployment_run_command_uses_role_separation():
    """
    The .replit deployment run command must start the scheduler with APP_ROLE=scheduler
    and gunicorn with APP_ROLE=web as separate processes.
    """
    source = _read(".replit")
    assert "APP_ROLE=scheduler" in source, (
        "Deployment run command must pass APP_ROLE=scheduler to the scheduler process"
    )
    assert "APP_ROLE=web" in source, (
        "Deployment run command must pass APP_ROLE=web to gunicorn"
    )
    assert "run_scheduler.py" in source, (
        "Deployment run command must reference scripts/run_scheduler.py"
    )
