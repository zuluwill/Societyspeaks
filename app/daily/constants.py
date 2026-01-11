"""
Constants for Daily Question functionality.

Centralizes shared values to follow DRY principles and make configuration easier.
"""

# =============================================================================
# VOTE MAPPINGS
# =============================================================================

# Maps string vote choices (from forms/URLs) to integer values (stored in DB)
VOTE_MAP = {
    'agree': 1,
    'disagree': -1,
    'unsure': 0
}

# Maps integer vote values to position labels (for responses/statements)
VOTE_TO_POSITION = {
    1: 'pro',
    -1: 'con',
    0: 'neutral'
}

# Maps integer vote values to human-readable labels
VOTE_LABELS = {
    1: 'Agree',
    -1: 'Disagree',
    0: 'Unsure'
}

# Maps vote choices to emojis for display
VOTE_EMOJIS = {
    'agree': '👍',
    'disagree': '👎',
    'unsure': '🤔'
}

# =============================================================================
# TOKEN CONFIGURATION
# =============================================================================

# Vote token expiration in hours (7 days)
# Longer than login tokens (48h) for better UX with email links
VOTE_TOKEN_EXPIRY_HOURS = 168

# Vote token expiration in seconds (for verification)
VOTE_TOKEN_EXPIRY_SECONDS = VOTE_TOKEN_EXPIRY_HOURS * 3600  # 604800

# Magic link token expiration in hours (for login/authentication)
MAGIC_TOKEN_EXPIRY_HOURS = 48

# =============================================================================
# GRACE PERIODS
# =============================================================================

# Number of days after question date that voting is still allowed
VOTE_GRACE_PERIOD_DAYS = 3

# =============================================================================
# UNSUBSCRIBE REASONS
# =============================================================================

VALID_UNSUBSCRIBE_REASONS = [
    'too_frequent',
    'not_interested', 
    'content_quality',
    'other',
    'not_specified'
]

# =============================================================================
# REASON VISIBILITY OPTIONS
# =============================================================================

VALID_VISIBILITY_OPTIONS = [
    'public_named',
    'public_anonymous',
    'private'
]

# Default visibility for email votes
DEFAULT_EMAIL_VOTE_VISIBILITY = 'public_anonymous'
