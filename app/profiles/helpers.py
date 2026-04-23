"""Shared helpers for profile create/edit flows."""

# Fields that should NEVER be copied from form to profile via the generic
# updater — images are handled separately (via object storage) and
# csrf/submit are WTForms plumbing.
_NON_PROFILE_FIELDS = frozenset({'csrf_token', 'submit', 'profile_image', 'banner_image', 'logo'})


def apply_form_to_profile(profile, form):
    """Copy every scalar form field onto the profile instance.

    Keeps create/edit routes DRY — when a new field (e.g. ``bluesky_url``) is
    added to the form + model, no route code needs to change.
    """
    for field_name, value in form.data.items():
        if field_name in _NON_PROFILE_FIELDS:
            continue
        if hasattr(profile, field_name):
            setattr(profile, field_name, value)
