"""Homepage / discovery helpers for guided journey country matching."""
from pathlib import Path

import pytest

from app.programmes.journey import (
    guided_journey_context_for_discussion,
    infer_journey_country_from_accept_language,
    journey_programme_country_lookup_key,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("UK", "united kingdom"),
        ("us", "united states"),
        ("United Kingdom", "united kingdom"),
        ("netherlands", "netherlands"),
        ("DE", "germany"),
        ("", None),
        (None, None),
        ("ZZ", None),
    ],
)
def test_journey_programme_country_lookup_key(raw, expected):
    assert journey_programme_country_lookup_key(raw) == expected


@pytest.mark.parametrize(
    "header,expected",
    [
        ("en-GB,en;q=0.9", "united kingdom"),
        ("en-US,en;q=0.8", "united states"),
        ("nl,en;q=0.9", "netherlands"),
        ("de-AT,de;q=0.9", "germany"),
        ("ga-IE,en;q=0.5", "ireland"),
        ("ja", "japan"),
        ("zh-CN", "china"),
        ("zh-TW,zh-CN;q=0.8", "china"),
        ("zh-TW", None),
        ("en", None),
        ("", None),
    ],
)
def test_infer_journey_country_from_accept_language(header, expected):
    assert infer_journey_country_from_accept_language(header) == expected


def test_journey_profile_country_codes_match_variant_metadata():
    """Profile lookup keys stay aligned with journey_variants (DRY guard)."""
    from app.programmes import journey as journey_mod
    from app.programmes.journey_variants import VARIANT_METADATA

    for vkey, meta in VARIANT_METADATA.items():
        if not meta.country:
            continue
        expected = meta.country.strip().lower()
        assert journey_mod._JOURNEY_PROFILE_COUNTRY_CODES.get(vkey) == expected, vkey
        assert journey_mod._JOURNEY_PROFILE_COUNTRY_CODES.get(expected) == expected
    assert journey_mod._JOURNEY_PROFILE_COUNTRY_CODES.get("gb") == "united kingdom"
    assert journey_mod._JOURNEY_PROFILE_COUNTRY_CODES.get("usa") == "united states"


def test_guided_journey_context_none_for_non_flagship_programme(app, db):
    from app.models import Discussion, Programme, User, generate_slug

    with app.app_context():
        u = User(username="gj_none_u", email="gj_none_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="Other programme",
            slug=generate_slug("other-programme-gj"),
            creator_id=u.id,
            themes=["Alpha"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d = Discussion(
            title="Alpha topic",
            slug=generate_slug("alpha-topic-gj"),
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="Alpha",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add(d)
        db.session.commit()
        assert guided_journey_context_for_discussion(d, u.id) is None


def test_discussion_has_linked_source_articles():
    from unittest.mock import MagicMock

    from app.programmes.journey import discussion_has_linked_source_articles

    empty = MagicMock()
    empty.source_article_links = []
    assert discussion_has_linked_source_articles(empty) is False

    unresolved = MagicMock()
    link = MagicMock()
    link.article = None
    unresolved.source_article_links = [link]
    assert discussion_has_linked_source_articles(unresolved) is False

    resolved = MagicMock()
    link_ok = MagicMock()
    link_ok.article = object()
    resolved.source_article_links = [link_ok]
    assert discussion_has_linked_source_articles(resolved) is True


def test_guided_journey_context_resolves_theme_index(app, db):
    from app.models import Discussion, Programme, User

    with app.app_context():
        u = User(username="gj_idx_u", email="gj_idx_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="Humanity test",
            slug="humanity-big-questions",
            creator_id=u.id,
            themes=["Climate", "Economy"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d_climate = Discussion(
            title="Climate discussion",
            slug="climate-disc-gj-test-unique",
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="Climate",
            geographic_scope="global",
            creator_id=u.id,
        )
        d_economy = Discussion(
            title="Economy discussion",
            slug="economy-disc-gj-test-unique",
            has_native_statements=True,
            programme_id=p.id,
            programme_theme="Economy",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add_all([d_climate, d_economy])
        db.session.commit()
        ctx = guided_journey_context_for_discussion(d_economy, u.id)
        assert ctx is not None
        assert ctx["theme_index"] == 2
        assert ctx["programme"].slug == "humanity-big-questions"
        assert ctx["theme_item"].discussion.id == d_economy.id
        assert ctx.get("has_source_articles") is False


def test_guided_journey_context_none_when_not_native(app, db):
    from app.models import Discussion, Programme, User, generate_slug

    with app.app_context():
        u = User(username="gj_legacy_u", email="gj_legacy_u@example.com", password="pw")
        db.session.add(u)
        db.session.flush()
        p = Programme(
            name="Humanity legacy",
            slug="humanity-big-questions",
            creator_id=u.id,
            themes=["T1"],
            visibility="public",
            status="active",
        )
        db.session.add(p)
        db.session.flush()
        d = Discussion(
            title="Legacy",
            slug=generate_slug("legacy-embed-gj"),
            has_native_statements=False,
            programme_id=p.id,
            programme_theme="T1",
            geographic_scope="global",
            creator_id=u.id,
        )
        db.session.add(d)
        db.session.commit()
        assert guided_journey_context_for_discussion(d, u.id) is None


def test_normalize_information_body_is_idempotent():
    from app.programmes.journey_seed import _normalize_information_body

    once = _normalize_information_body("Focus on **policy**.")
    twice = _normalize_information_body(once)
    assert once == twice
    assert once.startswith("**Your vote records what you think today**")


def test_get_curriculum_country_variants_have_reading_packs():
    """Every country journey theme gets Markdown optional reading + four vetted links."""
    from app.programmes.journey_seed import get_curriculum
    from app.programmes.journey_variants import VALID_VARIANTS

    for variant in sorted(VALID_VARIANTS - {"global"}):
        curriculum = get_curriculum(variant)
        assert len(curriculum) == 8, variant
        for spec in curriculum:
            theme = spec.get("theme")
            links = spec.get("information_links") or []
            body = spec.get("information_body") or ""
            assert len(links) == 4, f"{variant}/{theme}"
            assert all(isinstance(l, dict) and l.get("url", "").startswith("http") for l in links), (
                f"{variant}/{theme}"
            )
            assert "](" in body, f"{variant}/{theme} should include markdown links"


def test_get_curriculum_global_skips_reading_pack_merge():
    from app.programmes.journey_seed import _curriculum_global, get_curriculum

    baseline = _curriculum_global()[0].get("information_body")
    merged_first = get_curriculum("global")[0].get("information_body")
    assert merged_first == baseline


def test_journey_recap_template_inline_script_uses_csp_nonce():
    root = Path(__file__).resolve().parents[1]
    text = (root / "app/templates/programmes/journey_recap.html").read_text(encoding="utf-8")
    assert 'nonce="{{ csp_nonce() }}"' in text
