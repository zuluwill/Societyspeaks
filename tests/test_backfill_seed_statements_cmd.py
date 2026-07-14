"""
End-to-end tests for the `backfill-seed-statements` CLI command.

Exercises the real command via Flask's CLI runner against an in-memory DB, with
LLM API keys stripped so generation uses the deterministic fallback (no network).
"""

from app.models import User, Discussion, Statement, generate_slug


def _make_discussion(db, title, n_statements, creator=None):
    discussion = Discussion(
        title=title,
        slug=generate_slug(title),
        description="A civic topic under debate with room for many viewpoints.",
        has_native_statements=True,
        topic="Society",
        geographic_scope="global",
        creator_id=creator.id if creator else None,
    )
    db.session.add(discussion)
    db.session.flush()
    for i in range(n_statements):
        db.session.add(Statement(
            discussion_id=discussion.id,
            user_id=creator.id if creator else None,
            content=f"Existing seed statement number {i} for this discussion.",
            statement_type="claim",
            is_seed=True,
            mod_status=1,
        ))
    db.session.commit()
    return discussion


def _visible_count(discussion_id):
    return (
        Statement.query
        .filter_by(discussion_id=discussion_id, is_deleted=False)
        .filter(Statement.mod_status != -1)
        .count()
    )


def test_backfill_tops_up_single_discussion(app, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with app.app_context():
        creator = User(username="creator", email="creator@example.com", password="x")
        db.session.add(creator)
        db.session.flush()
        disc = _make_discussion(db, "Under-seeded discussion", n_statements=1, creator=creator)
        disc_id = disc.id

        result = app.test_cli_runner().invoke(
            args=["backfill-seed-statements", "--discussion-id", str(disc_id)]
        )

        assert result.exit_code == 0, result.output
        assert _visible_count(disc_id) == 7

        added = (
            Statement.query
            .filter_by(discussion_id=disc_id, source="ai_generated")
            .all()
        )
        assert len(added) == 6
        for s in added:
            assert s.is_seed is True
            assert s.mod_status == 1
            assert s.user_id == creator.id
            assert s.seed_stance in ("pro", "con", "neutral")


def test_backfill_dry_run_writes_nothing(app, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with app.app_context():
        disc = _make_discussion(db, "Dry run discussion", n_statements=2)
        disc_id = disc.id

        result = app.test_cli_runner().invoke(
            args=["backfill-seed-statements", "--discussion-id", str(disc_id), "--dry-run"]
        )

        assert result.exit_code == 0, result.output
        assert "would add" in result.output
        assert _visible_count(disc_id) == 2  # unchanged


def test_backfill_skips_discussions_already_at_floor(app, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with app.app_context():
        disc = _make_discussion(db, "Healthy discussion", n_statements=7)
        disc_id = disc.id

        result = app.test_cli_runner().invoke(args=["backfill-seed-statements"])

        assert result.exit_code == 0, result.output
        assert _visible_count(disc_id) == 7


def test_backfill_ignores_polis_embed_discussions(app, db, monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with app.app_context():
        embed = Discussion(
            title="Polis embed discussion",
            slug=generate_slug("Polis embed discussion"),
            has_native_statements=False,
            topic="Society",
            geographic_scope="global",
        )
        db.session.add(embed)
        db.session.commit()
        embed_id = embed.id

        result = app.test_cli_runner().invoke(args=["backfill-seed-statements"])

        assert result.exit_code == 0, result.output
        # Embed discussions use pol.is, not native statements — must be untouched.
        assert _visible_count(embed_id) == 0
