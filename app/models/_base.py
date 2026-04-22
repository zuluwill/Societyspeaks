"""
Shared utilities for the app.models package.

Holds helpers that multiple domain submodules depend on but that don't
belong to any single domain. Keeping them here avoids submodule-to-
submodule imports for plumbing.

Moved here from app/models.py as part of the models-split refactor.
"""

import re

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
