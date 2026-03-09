"""
Dependency-light contract tests for concurrent consensus job claiming.

This suite intentionally uses AST/source assertions (not runtime Flask app imports)
so it remains stable in minimal test environments without full app dependencies.

Locking guarantees covered:
  - Postgres branch uses with_for_update(skip_locked=True)
  - Non-Postgres fallback does not attempt FOR UPDATE
  - Job claim path transitions to RUNNING before heavy processing
"""
import ast
from pathlib import Path

JOBS_PATH = Path(__file__).resolve().parents[1] / "app" / "discussions" / "jobs.py"


# ---------------------------------------------------------------------------
# AST helpers (same pattern as test_statement_vote_upsert_retry.py)
# ---------------------------------------------------------------------------

def _tree() -> ast.Module:
    return ast.parse(JOBS_PATH.read_text(encoding="utf-8"))


def _get_function(name: str) -> ast.FunctionDef:
    for node in ast.walk(_tree()):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Function {name!r} not found in {JOBS_PATH.name}")


def _has_call_in_subtree(root: ast.AST, method_name: str) -> bool:
    """Return True if any Call node in root invokes method_name as an attribute."""
    for node in ast.walk(root):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == method_name
        ):
            return True
    return False


def _has_keyword_value(call_node: ast.Call, keyword: str, value) -> bool:
    """Return True if the Call has keyword=value."""
    for kw in call_node.keywords:
        if kw.arg == keyword and isinstance(kw.value, ast.Constant) and kw.value.value == value:
            return True
    return False


def _find_with_for_update_calls(root: ast.AST):
    """Yield all Call nodes that invoke .with_for_update(...)."""
    for node in ast.walk(root):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == 'with_for_update'
        ):
            yield node


def _get_if_dialect_branches(func: ast.FunctionDef):
    """
    Return (postgres_branch_body, else_body) for the
    `if bind.dialect.name == 'postgresql':` guard inside func.
    Raises AssertionError if not found.
    """
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        # Match: bind.dialect.name == 'postgresql'
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Attribute)
            and test.left.attr == 'name'
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == 'postgresql'
            and test.ops
            and isinstance(test.ops[0], ast.Eq)
        ):
            return node.body, node.orelse
    raise AssertionError(
        "Dialect guard `if bind.dialect.name == 'postgresql':` not found "
        f"in function 'process_next_consensus_job' in {JOBS_PATH.name}"
    )


# ---------------------------------------------------------------------------
# AST structural tests
# ---------------------------------------------------------------------------

def test_process_next_job_has_dialect_guard():
    """process_next_consensus_job must check dialect before choosing query strategy."""
    func = _get_function('process_next_consensus_job')
    # Will raise AssertionError if the guard is missing.
    _get_if_dialect_branches(func)


def test_postgres_branch_uses_skip_locked():
    """
    In the Postgres dialect branch, the query must call
    .with_for_update(skip_locked=True) to prevent concurrent workers from
    claiming the same job.
    """
    func = _get_function('process_next_consensus_job')
    pg_body, _ = _get_if_dialect_branches(func)

    # Build a dummy Module wrapping just the Postgres branch so we can walk it.
    wrapper = ast.Module(body=pg_body, type_ignores=[])

    wfu_calls = list(_find_with_for_update_calls(wrapper))
    assert wfu_calls, (
        "No .with_for_update() call found in the Postgres branch of "
        "process_next_consensus_job — SKIP LOCKED guard is missing."
    )

    skip_locked_set = any(
        _has_keyword_value(c, 'skip_locked', True) for c in wfu_calls
    )
    assert skip_locked_set, (
        ".with_for_update() found in Postgres branch but skip_locked=True "
        "is not set.  Without it concurrent workers can double-claim jobs."
    )


def test_sqlite_fallback_branch_has_no_with_for_update():
    """
    The SQLite else-branch must NOT use with_for_update (SQLite raises
    CompileError if you attempt FOR UPDATE syntax).
    """
    func = _get_function('process_next_consensus_job')
    _, else_body = _get_if_dialect_branches(func)

    wrapper = ast.Module(body=else_body, type_ignores=[])
    wfu_calls = list(_find_with_for_update_calls(wrapper))
    assert not wfu_calls, (
        ".with_for_update() found in the SQLite fallback branch of "
        "process_next_consensus_job — this will raise CompileError on SQLite."
    )


def test_skip_locked_not_applied_to_stale_job_sweep():
    """
    mark_stale_consensus_jobs() loads RUNNING jobs to sweep timeouts.
    It does not need row-level locking (it only updates, never claims).
    """
    func = _get_function('mark_stale_consensus_jobs')
    wfu_calls = list(_find_with_for_update_calls(func))
    assert not wfu_calls, (
        "mark_stale_consensus_jobs() unexpectedly uses with_for_update — "
        "it is not a job-claiming path and does not need row locking."
    )


def test_claim_path_sets_running_state_before_cluster_call():
    """
    Contract: after a job is selected, process_next_consensus_job must mark it
    RUNNING before plan check / heavy analysis execution.
    """
    source = JOBS_PATH.read_text(encoding="utf-8")
    running_assign = "job.status = ConsensusJob.STATUS_RUNNING"
    planning_call = "get_consensus_execution_plan(job.discussion_id, db)"
    run_call = "run_consensus_analysis(job.discussion_id, db, method='agglomerative')"

    assert running_assign in source, "Job claim path does not set RUNNING status."
    assert planning_call in source, "Expected execution-plan pre-check call is missing."
    assert run_call in source, "Expected run_consensus_analysis call is missing."
    assert source.index(running_assign) < source.index(planning_call), (
        "RUNNING status must be set before execution planning check."
    )
    assert source.index(running_assign) < source.index(run_call), (
        "RUNNING status must be set before heavy analysis execution."
    )
