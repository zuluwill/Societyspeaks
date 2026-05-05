"""Unified anonymous voter identity (cross-blueprint consistency)."""

import secrets


def test_voter_fingerprint_matches_legacy_daily_cookie(app):
    cid = secrets.token_hex(32)
    with app.test_request_context("/", headers={"Cookie": f"daily_client_id={cid}"}):
        from app.lib import vote_identity

        expected = vote_identity.fingerprint_from_client_id(cid)
        assert vote_identity.get_voter_fingerprint() == expected


def test_daily_lookup_aliases_include_statement_and_daily_hashes(app):
    cid_stmt = secrets.token_hex(32)
    cid_daily = secrets.token_hex(32)
    with app.test_request_context(
        "/",
        headers={
            "Cookie": (
                f"statement_client_id={cid_stmt}; daily_client_id={cid_daily}"
            )
        },
    ):
        from app.lib import vote_identity

        aliases = vote_identity.anonymous_fingerprint_aliases_for_daily_lookup()
        assert vote_identity.fingerprint_from_client_id(cid_stmt) in aliases
        assert vote_identity.fingerprint_from_client_id(cid_daily) in aliases
        assert vote_identity.get_voter_fingerprint() in aliases


def test_daily_lookup_aliases_include_embed_fingerprint_from_json(app):
    cid = secrets.token_hex(32)
    embed_raw = "partner-embed-session-identifier-string"
    with app.test_request_context(
        "/",
        method="POST",
        json={"embed_fingerprint": embed_raw},
        headers={"Cookie": f"ss_voter_client_id={cid}"},
    ):
        from app.discussions.statements import normalize_embed_fingerprint
        from app.lib import vote_identity

        aliases = vote_identity.anonymous_fingerprint_aliases_for_daily_lookup()
        assert vote_identity.fingerprint_from_client_id(cid) in aliases
        assert normalize_embed_fingerprint(embed_raw) in aliases
