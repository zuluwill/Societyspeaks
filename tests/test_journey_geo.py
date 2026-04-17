"""Homepage / discovery helpers for guided journey country matching."""
import pytest

from app.programmes.journey import (
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
