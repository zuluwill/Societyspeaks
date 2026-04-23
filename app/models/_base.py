"""
Shared utilities for the app.models package.

Holds helpers that multiple domain submodules depend on but that don't
belong to any single domain. Keeping them here avoids submodule-to-
submodule imports for plumbing.

Moved here from app/models.py as part of the models-split refactor.
"""

import random
import re
import string

from unidecode import unidecode


def generate_slug(name):
    """Generate a URL-friendly slug from a string."""
    if not name:
        return ""

    # Convert to lowercase and normalize unicode characters
    name = str(name).lower()
    name = unidecode(name)

    # Replace non-alphanumeric characters with hyphens
    name = re.sub(r'[^a-z0-9]+', '-', name)

    # Remove leading/trailing hyphens
    name = name.strip('-')

    # Replace multiple consecutive hyphens with a single hyphen
    name = re.sub(r'-+', '-', name)

    return name


def get_unique_slug(model_class, base_slug, max_attempts=100, exclude_id=None):
    """Return a slug that does not collide with any existing row on `model_class`.

    Appends numeric suffixes for the first 10 attempts (``-1`` … ``-10``), then
    falls back to random 6-char suffixes. Pass ``exclude_id`` when renaming an
    existing row so the row does not collide with itself.
    """
    slug = base_slug
    for attempt in range(max_attempts):
        query = model_class.query.filter_by(slug=slug)
        if exclude_id is not None:
            query = query.filter(model_class.id != exclude_id)
        if query.first() is None:
            return slug

        if attempt < 10:
            slug = f"{base_slug}-{attempt + 1}"
        else:
            suffix = ''.join(random.choices(string.ascii_lowercase + string.digits, k=6))
            slug = f"{base_slug}-{suffix}"

    raise ValueError(f"Unable to generate unique slug after {max_attempts} attempts")


def generate_unique_slug(model_class, name, fallback='item', exclude_id=None):
    """Convenience wrapper: slugify ``name`` then make it unique on ``model_class``.

    Falls back to ``fallback`` when ``name`` slugifies to an empty string.
    """
    base = generate_slug(name) or fallback
    return get_unique_slug(model_class, base, exclude_id=exclude_id)
