"""Anonymous guided-journey progress aligns with StatementVote + visible statements."""

from app.models import Discussion, Programme, Statement, StatementVote, User, generate_slug
from app.programmes.journey import (
    anon_statement_votes_detail_batch,
    build_journey_progress,
)


def test_build_journey_progress_counts_anonymous_votes(app, db):
    with app.app_context():
        u = User(username="jp_anon_u", email="jp_anon_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="JP anon prog",
            slug=generate_slug("JP anon prog"),
            creator_id=u.id,
            themes=["T1"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d = Discussion(
            title="Theme one",
            slug=generate_slug("jp-anon-d1"),
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="T1",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add(d)
        db.session.flush()
        s1 = Statement(
            discussion_id=d.id,
            user_id=u.id,
            content="Statement one with enough characters for validation.",
        )
        s2 = Statement(
            discussion_id=d.id,
            user_id=u.id,
            content="Statement two with enough characters for validation.",
        )
        db.session.add_all([s1, s2])
        db.session.flush()
        fp = "a" * 64
        db.session.add(
            StatementVote(
                statement_id=s1.id,
                discussion_id=d.id,
                user_id=None,
                session_fingerprint=fp,
                vote=1,
            )
        )
        db.session.commit()

        prog = build_journey_progress(p, None, discussions=[d], anon_fingerprint_aliases=[fp])
        assert prog["theme_items"][0].statement_total == 2
        assert prog["theme_items"][0].user_votes == 1
        assert prog["theme_items"][0].is_complete is False


def test_build_journey_progress_anon_ignores_hidden_statement_votes(app, db):
    with app.app_context():
        u = User(username="jp_vis_u", email="jp_vis_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="JP visibility prog",
            slug=generate_slug("JP visibility prog"),
            creator_id=u.id,
            themes=["T1"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d = Discussion(
            title="Visibility theme",
            slug=generate_slug("jp-vis-d"),
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="T1",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add(d)
        db.session.flush()
        s_ok = Statement(
            discussion_id=d.id,
            user_id=u.id,
            content="Visible statement with enough characters here.",
        )
        s_bad = Statement(
            discussion_id=d.id,
            user_id=u.id,
            content="Moderated away statement text goes here long.",
            mod_status=-1,
        )
        db.session.add_all([s_ok, s_bad])
        db.session.flush()
        fp = "b" * 64
        db.session.add_all(
            [
                StatementVote(
                    statement_id=s_ok.id,
                    discussion_id=d.id,
                    user_id=None,
                    session_fingerprint=fp,
                    vote=1,
                ),
                StatementVote(
                    statement_id=s_bad.id,
                    discussion_id=d.id,
                    user_id=None,
                    session_fingerprint=fp,
                    vote=-1,
                ),
            ]
        )
        db.session.commit()

        prog = build_journey_progress(p, None, discussions=[d], anon_fingerprint_aliases=[fp])
        assert prog["theme_items"][0].statement_total == 1
        assert prog["theme_items"][0].user_votes == 1


def test_anon_batch_counts_distinct_statements_across_fingerprint_aliases(app, db):
    """Legacy alias merge: two cookies → two rows on one statement → count once."""
    with app.app_context():
        u = User(username="jp_dedupe_u", email="jp_dedupe_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="JP dedupe prog",
            slug=generate_slug("JP dedupe prog"),
            creator_id=u.id,
            themes=["T1"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d = Discussion(
            title="Dedupe theme",
            slug=generate_slug("jp-dedupe-d"),
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="T1",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add(d)
        db.session.flush()
        s1 = Statement(
            discussion_id=d.id,
            user_id=u.id,
            content="Single statement with enough characters for validation.",
        )
        db.session.add(s1)
        db.session.flush()
        fp_a = "c" * 64
        fp_d = "d" * 64
        db.session.add_all(
            [
                StatementVote(
                    statement_id=s1.id,
                    discussion_id=d.id,
                    user_id=None,
                    session_fingerprint=fp_a,
                    vote=1,
                ),
                StatementVote(
                    statement_id=s1.id,
                    discussion_id=d.id,
                    user_id=None,
                    session_fingerprint=fp_d,
                    vote=-1,
                ),
            ]
        )
        db.session.commit()

        prog = build_journey_progress(
            p, None, discussions=[d], anon_fingerprint_aliases=[fp_a, fp_d]
        )
        assert prog["theme_items"][0].user_votes == 1

        detail = anon_statement_votes_detail_batch([fp_a, fp_d], [d.id])
        assert len(detail[d.id]) == 1
