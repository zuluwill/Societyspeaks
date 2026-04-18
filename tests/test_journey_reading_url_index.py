"""URL extraction for journey reading packs (DRY with verify script)."""

from app.programmes.journey_reading_url_index import (
    iter_reading_pack_url_refs,
    normalize_url_for_dedup,
    refs_by_normalized_url,
)


def test_normalize_url_for_dedup_strips_fragment_and_lowercases_host():
    a = "https://Example.ORG/path#frag"
    b = "https://example.org/path"
    assert normalize_url_for_dedup(a) == normalize_url_for_dedup(b)


def test_iter_reading_pack_url_refs_merges_markdown_and_information_links():
    packs = {
        "uk": {
            "Climate & planet": {
                "body": "See [ONS](https://www.ons.gov.uk/climate) for data.",
                "links": [{"label": "Met Office", "url": "https://www.metoffice.gov.uk/"}],
            }
        }
    }
    refs = list(iter_reading_pack_url_refs(packs))
    assert len(refs) == 2
    sources = {r.source for r in refs}
    assert sources == {"markdown", "information_link"}
    urls = {r.url for r in refs}
    assert "https://www.ons.gov.uk/climate" in urls
    assert "https://www.metoffice.gov.uk/" in urls


def test_refs_by_normalized_url_deduplicates_same_host_and_path():
    packs = {
        "uk": {
            "Climate & planet": {
                "body": "[a](https://EXAMPLE.ORG/foo)",
                "links": [{"label": "b", "url": "https://example.org/foo"}],
            }
        }
    }
    grouped = refs_by_normalized_url(packs)
    assert len(grouped) == 1


def test_reading_packs_for_link_audit_includes_global_curriculum():
    from app.programmes.journey_reading_url_index import (
        reading_packs_for_link_audit,
        refs_by_normalized_url,
    )

    country_only = refs_by_normalized_url()
    full = refs_by_normalized_url(reading_packs_for_link_audit())
    packs = reading_packs_for_link_audit()
    assert "global" in packs
    assert "uk" in packs
    assert len(full) >= len(country_only)


def test_live_reading_packs_have_urls():
    """Integration: real READING_PACKS must yield at least one URL per variant."""
    from app.programmes.journey_reading_enrichment import READING_PACKS

    for variant, themes in READING_PACKS.items():
        for theme, pack in themes.items():
            refs = list(iter_reading_pack_url_refs({variant: {theme: pack}}))
            assert len(refs) >= 4, f"{variant}/{theme} expected markdown + 4 links"
