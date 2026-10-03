"""Shared discussion and consensus threshold constants."""

# Consensus analysis readiness thresholds.
CONSENSUS_MIN_PARTICIPANTS = 7
CONSENSUS_MIN_TOTAL_VOTES = 20
CONSENSUS_MIN_VOTES_PER_STATEMENT = 3

# UX + seed-generation floor (not an analysis hard gate).
# Pol.is recommends at least 10 seed comments to map the opinion space.
CONSENSUS_RECOMMENDED_STATEMENT_COUNT = 10

# Viewer participation gate (anti-anchoring); separate from analysis readiness.
CONSENSUS_VIEW_RESULTS_MIN_VOTES = 5


def consensus_thresholds_dict():
    """Template-friendly threshold payload."""
    return {
        "min_participants": CONSENSUS_MIN_PARTICIPANTS,
        "min_total_votes": CONSENSUS_MIN_TOTAL_VOTES,
        "min_votes_per_statement": CONSENSUS_MIN_VOTES_PER_STATEMENT,
        "recommended_statements": CONSENSUS_RECOMMENDED_STATEMENT_COUNT,
        "view_results_min_votes": CONSENSUS_VIEW_RESULTS_MIN_VOTES,
    }


# ── Statement-level results ─────────────────────────────────────────────────
# One statement, one verdict, from the shares of everyone who voted on it
# (unsure included). See ``app/lib/statement_results.py``.

# Below this many votes a statement is reported as counts, with no called
# verdict. Five is the smallest room in which a unanimous result is still a
# stable majority. Smaller rooms see the running counts, not a conclusion.
RESULT_MIN_VOTES = 5
# "Agrees" / "disagrees": the 95% lower bound of that share reaches a majority.
RESULT_MAJORITY_SHARE = 0.50
# "Unsure": unsure is the largest response and its lower bound reaches a third.
RESULT_UNSURE_SHARE = 1 / 3
# "Split": both sides are substantial and close to each other.
RESULT_SPLIT_MIN_SIDE_SHARE = 0.35
RESULT_SPLIT_MAX_GAP = 0.15
