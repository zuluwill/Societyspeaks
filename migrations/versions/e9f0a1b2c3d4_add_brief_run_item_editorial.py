"""Promote BriefRunItem cluster/context data from markdown markers to columns.

Adds three columns on ``brief_run_item``:

- ``cluster_also_covered`` (JSONB): list of ``{name, url}`` for sibling stories
  in the same headline cluster. Lets the email/web template render the
  "Also covered by …" line without parsing the markdown.
- ``context_label`` (String): editorial label for the context box
  ("What This Means", "Market Impact", …).
- ``context_insight`` (Text): the 1-2 sentence insight that goes in the box.

Backfill: existing rows encoded this data as inline markers inside
``content_markdown`` — ``[ALSO_COVERED:name|url;name|url]`` followed by
``[Label] insight\\n\\n…rest…``. The backfill parses those markers, populates
the new columns, and strips the markers from ``content_markdown`` so the new
renderer doesn't double-render them.

Revision ID: e9f0a1b2c3d4
Revises: m7a8g9i0c1l2
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision = 'e9f0a1b2c3d4'
down_revision = 'm7a8g9i0c1l2'
branch_labels = None
depends_on = None


_CONTEXT_LABELS = (
    'What This Means', 'Key Challenge', 'Market Impact',
    'Policy Context', 'Why It Matters',
)


def _parse_also_covered(markdown: str) -> tuple[list[dict], str]:
    """Extract ``[ALSO_COVERED:...]`` payload. Mirrors generator.py parser."""
    if not markdown.startswith('[ALSO_COVERED:') or ']\n\n' not in markdown:
        return [], markdown
    end = markdown.index(']\n\n')
    payload = markdown[len('[ALSO_COVERED:'):end]
    rest = markdown[end + 3:]
    also: list[dict] = []
    for part in payload.split(';'):
        if '|' in part:
            name, url = part.split('|', 1)
            if name.strip():
                also.append({'name': name.strip(), 'url': url.strip()})
    return also, rest


def _parse_context(markdown: str) -> tuple[str | None, str | None, str]:
    """Extract ``[Label] insight\\n\\n...`` prefix from markdown."""
    if not markdown.startswith('[') or ']' not in markdown:
        return None, None, markdown
    bracket_end = markdown.index(']')
    label = markdown[1:bracket_end]
    if label not in _CONTEXT_LABELS:
        # Don't false-positive on headings or other bracket prefixes.
        return None, None, markdown
    rest = markdown[bracket_end + 2:]
    if '\n\n' in rest:
        insight, remainder = rest.split('\n\n', 1)
    else:
        insight, remainder = rest, ''
    return label, insight.strip() or None, remainder


def upgrade():
    bind = op.get_bind()
    bind.execute(sa.text(
        "ALTER TABLE brief_run_item ADD COLUMN IF NOT EXISTS cluster_also_covered JSONB"
    ))
    bind.execute(sa.text(
        "ALTER TABLE brief_run_item ADD COLUMN IF NOT EXISTS context_label VARCHAR(100)"
    ))
    bind.execute(sa.text(
        "ALTER TABLE brief_run_item ADD COLUMN IF NOT EXISTS context_insight TEXT"
    ))

    rows = bind.execute(sa.text(
        "SELECT id, content_markdown FROM brief_run_item "
        "WHERE content_markdown LIKE '[%' "
    )).fetchall()

    updates: list[dict] = []
    for row in rows:
        md = row.content_markdown or ''
        also, after_also = _parse_also_covered(md)
        label, insight, after_ctx = _parse_context(after_also)
        if not also and not label:
            continue
        updates.append({
            'id': row.id,
            'cluster': also or None,
            'label': label,
            'insight': insight,
            'cleaned': after_ctx,
        })

    if updates:
        bind.execute(
            sa.text(
                "UPDATE brief_run_item SET "
                "cluster_also_covered = CAST(:cluster AS JSONB), "
                "context_label = :label, "
                "context_insight = :insight, "
                "content_markdown = :cleaned "
                "WHERE id = :id"
            ),
            [
                {
                    'id': u['id'],
                    'cluster': _json_dump(u['cluster']),
                    'label': u['label'],
                    'insight': u['insight'],
                    'cleaned': u['cleaned'],
                }
                for u in updates
            ],
        )


def downgrade():
    # Best-effort: re-encode the columns back into markdown so a downgrade
    # leaves the data intact for the old renderer.
    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, content_markdown, cluster_also_covered, "
        "context_label, context_insight FROM brief_run_item "
        "WHERE cluster_also_covered IS NOT NULL OR context_label IS NOT NULL"
    )).fetchall()
    for row in rows:
        prefix = ''
        cluster = row.cluster_also_covered
        if cluster:
            pairs = ';'.join(
                f"{c.get('name','')}|{c.get('url','')}"
                for c in cluster
                if c.get('name')
            )
            if pairs:
                prefix += f"[ALSO_COVERED:{pairs}]\n\n"
        if row.context_label and row.context_insight:
            prefix += f"[{row.context_label}] {row.context_insight}\n\n"
        if prefix:
            new_md = prefix + (row.content_markdown or '')
            bind.execute(
                sa.text("UPDATE brief_run_item SET content_markdown = :md WHERE id = :id"),
                {'md': new_md, 'id': row.id},
            )

    op.drop_column('brief_run_item', 'context_insight')
    op.drop_column('brief_run_item', 'context_label')
    op.drop_column('brief_run_item', 'cluster_also_covered')


def _json_dump(value):
    import json
    return json.dumps(value) if value is not None else None
