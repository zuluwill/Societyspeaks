# app/admin/utils.py


def escape_like(value):
    """Escape SQL LIKE/ILIKE wildcard characters in user-provided search text.

    Use alongside SQLAlchemy's ilike(..., escape='\\\\') so the database treats
    backslash as the escape character, matching the patterns produced here.
    """
    return (value or '').replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
