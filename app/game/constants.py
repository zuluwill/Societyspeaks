"""Society Play constants."""

# Back-compat alias — prefer daily_service.scheduled_scenario_slug().
SLICE_SCENARIO_SLUG = 'debt-inherited'

STAT_VISIBLE = ('prosperity', 'trust', 'fairness', 'stability')
STAT_HIDDEN = ('future', 'debt_stress', 'autonomy', 'fragility')
STAT_ALL = STAT_VISIBLE + STAT_HIDDEN

STAT_LABELS = {
    'prosperity': 'Prosperity',
    'trust': 'Trust',
    'fairness': 'Fairness',
    'stability': 'Stability',
    'future': 'Future',
    'debt_stress': 'Debt pressure',
    'autonomy': 'Autonomy',
    'fragility': 'Fragility',
}

DEFAULT_SOCIETY_NAME = 'Your society'

GAME_RUN_STATUS_IN_PROGRESS = 'in_progress'
GAME_RUN_STATUS_COMPLETED = 'completed'
GAME_RUN_STATUS_ABANDONED = 'abandoned'
