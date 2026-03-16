"""Shared discussion and consensus threshold constants."""

# Consensus analysis readiness thresholds.
CONSENSUS_MIN_PARTICIPANTS = 7
CONSENSUS_MIN_TOTAL_VOTES = 20
CONSENSUS_MIN_VOTES_PER_STATEMENT = 3

# UX guidance threshold (not a hard gate).
CONSENSUS_RECOMMENDED_STATEMENT_COUNT = 7

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
