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
    assert "'method': 'sampled_incremental_clustered'" in source
    assert "participant_sampling_strategy" in source
    assert "stability_mean_ari" in source


def test_consensus_routes_use_execution_plan_for_queueing():
    source = _read("app/discussions/consensus.py")
    assert "get_consensus_execution_plan" in source
    assert "analysis_mode" in source
    assert "_assess_analysis_publishability" in source
    assert "CONSENSUS_OVERSIZE_MIN_STABILITY_ARI" in source


def test_jobs_use_execution_plan_not_only_can_cluster():
    source = _read("app/discussions/jobs.py")
    assert "get_consensus_execution_plan" in source
    assert "plan['is_ready']" in source


def test_consensus_export_respects_publishability_gate():
    source = _read("app/discussions/consensus.py")
    # Verify the export route exists
    assert "@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/export')" in source

    # Verify the publishability gate appears inside the export function body.
    # Slice from the export route decorator to the next route decorator to isolate the function.
    export_start = source.index(
        "@consensus_bp.route('/api/discussions/<int:discussion_id>/consensus/export')"
    )
    next_route = source.find("@consensus_bp.route(", export_start + 1)
    export_body = source[export_start:next_route] if next_route != -1 else source[export_start:]

    assert "_assess_analysis_publishability(analysis)" in export_body, (
        "export_analysis must call _assess_analysis_publishability"
    )
    assert "'error': 'analysis_withheld'" in export_body, (
        "export_analysis must return analysis_withheld error"
    )
    assert "}), 409" in export_body, (
        "export_analysis must return 409 for withheld analyses"
    )


def test_startup_validates_consensus_oversize_config():
    source = _read("app/__init__.py")
    assert "def _validate_consensus_oversize_config(app):" in source
    assert "_validate_consensus_oversize_config(app)" in source
    assert "CONSENSUS_OVERSIZE_MIN_STABILITY_RUNS cannot exceed " in source
    assert "CONSENSUS_OVERSIZE_STABILITY_RUNS" in source


def test_single_stability_run_returns_full_metrics_not_empty_dict():
    """
    When CONSENSUS_OVERSIZE_STABILITY_RUNS=1, _compute_oversize_stability_metrics
    must return a complete dict with stability_mean_ari=1.0 (not a bare
    {'stability_runs': 1}) so the publishability gate does not default ARI to
    0.0 and permanently withhold all oversize analyses.
    """
    source = _read("app/lib/consensus_engine.py")
    # Find the early-return branch for runs <= 1
    assert "if runs <= 1:" in source
    # Verify the fix: stability_mean_ari must be present in the single-run return
    early_return_start = source.index("if runs <= 1:")
    early_return_block = source[early_return_start:early_return_start + 600]
    assert "'stability_mean_ari': 1.0" in early_return_block, (
        "_compute_oversize_stability_metrics must return stability_mean_ari=1.0 "
        "for single-run mode, not leave it absent (which defaults to 0.0 in the "
        "publishability gate and permanently withholds analyses)"
    )
