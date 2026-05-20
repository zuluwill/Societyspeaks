"""Backfill InputSource political_leaning + is_verified from NewsSource.

Until ``app/briefing/source_bridge.py`` shipped, ``create_input_source_from_news_source``
created bare RSS rows without copying the curated metadata. That meant the
paid brief's coverage perspective block had no signal for existing users
even after the bridge was added — only newly-created sources would carry
political_leaning forward.

This is a one-shot data migration: for every ``input_source`` with
``owner_type='system'`` that matches a ``news_source`` by name, copy across
``political_leaning`` (when the InputSource has none) and stamp
``is_verified=true``. Anything the user added directly (non-system) is
left alone — we have no source of truth for those.

Safe to re-run: only updates rows where ``political_leaning IS NULL`` so a
later edit by an admin sticks.

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-05-20
"""
from alembic import op
import sqlalchemy as sa


revision = 'f0a1b2c3d4e5'
down_revision = 'e9f0a1b2c3d4'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()

    # Backfill political_leaning where unset (don't clobber admin overrides).
    bind.execute(sa.text(
        """
        UPDATE input_source AS ins
        SET political_leaning = ns.political_leaning
        FROM news_source AS ns
        WHERE ins.owner_type = 'system'
          AND ins.name = ns.name
          AND ins.political_leaning IS NULL
          AND ns.political_leaning IS NOT NULL
        """
    ))

    # Stamp is_verified on every system-owned source that matches a curated
    # NewsSource — those have been editorially vetted by definition.
    bind.execute(sa.text(
        """
        UPDATE input_source AS ins
        SET is_verified = true
        FROM news_source AS ns
        WHERE ins.owner_type = 'system'
          AND ins.name = ns.name
          AND ins.is_verified IS DISTINCT FROM true
        """
    ))

    # Where origin_type is the loose default ('user'), upgrade to 'admin' for
    # system sources sourced from the curated allowlist. The application-level
    # bridge already does this for new rows; this catches the legacy backlog.
    bind.execute(sa.text(
        """
        UPDATE input_source AS ins
        SET origin_type = 'admin'
        FROM news_source AS ns
        WHERE ins.owner_type = 'system'
          AND ins.name = ns.name
          AND (ins.origin_type IS NULL OR ins.origin_type = 'user')
        """
    ))


def downgrade():
    # Data migration — not reversible. Schema is unchanged so a no-op
    # downgrade is the correct behaviour here.
    pass
