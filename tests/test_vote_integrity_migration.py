from pathlib import Path


def test_vote_integrity_migration_exists():
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "v1w2x3y4z5a6_reinstate_vote_integrity_constraints.py"
    assert migration_path.exists(), "Phase 0 integrity migration is missing"


def test_vote_integrity_migration_contains_required_constraints_and_repairs():
    migration_path = Path(__file__).resolve().parents[1] / "migrations" / "versions" / "v1w2x3y4z5a6_reinstate_vote_integrity_constraints.py"
    content = migration_path.read_text(encoding="utf-8")

    required_markers = [
        "CREATE UNIQUE INDEX uq_statement_user_vote",
        "WHERE user_id IS NOT NULL",
        "CREATE UNIQUE INDEX uq_statement_session_vote",
        "WHERE session_fingerprint IS NOT NULL",
        "CREATE UNIQUE INDEX uq_discussion_participant_user",
        "PARTITION BY statement_id, user_id",
        "PARTITION BY statement_id, session_fingerprint",
        "PARTITION BY discussion_id, user_id",
        "UPDATE statement s",
        "vote_count_agree",
        "vote_count_disagree",
        "vote_count_unsure",
    ]

    missing = [marker for marker in required_markers if marker not in content]
    assert not missing, f"Integrity migration is missing required SQL markers: {missing}"

