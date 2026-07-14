"""
Behavioural tests for the seed-statement floor guarantees.

Regression cover for the bug where discussions were published with as few as one
seed statement: an over-aggressive specificity gate discarded otherwise-valid
statements, and nothing topped the set back up to the recommended count.
"""

import json

import pytest

from app.discussions.thresholds import CONSENSUS_RECOMMENDED_STATEMENT_COUNT
from app.trending import seed_generator
from app.trending.seed_generator import (
    DEFAULT_SEED_COUNT,
    _extract_statements_payload,
    _fallback_seed_statements,
    _parse_and_validate_statements,
    generate_seed_statements,
)


def test_default_seed_count_matches_consensus_threshold():
    assert DEFAULT_SEED_COUNT == CONSENSUS_RECOMMENDED_STATEMENT_COUNT == 7


# ---------------------------------------------------------------------------
# _parse_and_validate_statements: never shrinks valid statements
# ---------------------------------------------------------------------------

def test_parse_keeps_statements_that_fail_the_specificity_gate():
    """Non-specific but valid statements must survive (the 1-statement bug)."""
    payload = json.dumps([
        # passes _looks_specific_enough (" should ", " because ")
        {"content": "Local councils should expand cycle lanes because congestion harms residents.",
         "position": "pro"},
        # no modal keyword -> fails the gate, but is still a valid statement
        {"content": "Cars remain the most practical option for many rural families today.",
         "position": "con"},
        # no modal keyword -> fails the gate
        {"content": "How do new cycle lanes affect small high-street traders over time?",
         "position": "neutral"},
    ])

    result = _parse_and_validate_statements(payload, count=7)

    assert len(result) == 3, "valid statements must not be dropped by the gate"
    contents = {r["content"] for r in result}
    assert any("Cars remain" in c for c in contents)
    assert any("high-street traders" in c for c in contents)


def test_parse_deduplicates_repeated_content():
    payload = json.dumps([
        {"content": "Councils should invest in safer junctions because collisions are rising.",
         "position": "pro"},
        {"content": "Councils should invest in safer junctions because collisions are rising.",
         "position": "pro"},
    ])

    result = _parse_and_validate_statements(payload, count=7)

    assert len(result) == 1


def test_parse_trims_to_requested_count():
    payload = json.dumps([
        {"content": f"Statement number {i} should change because the evidence is clear now.",
         "position": "pro"}
        for i in range(10)
    ])

    result = _parse_and_validate_statements(payload, count=7)

    assert len(result) == 7


def test_extract_recovers_complete_objects_from_truncated_json():
    truncated = (
        '[{"content": "Councils should expand cycle lanes because congestion is rising.", '
        '"position": "pro"}, {"content": "Rural families still rely on cars every day.", '
        '"position": "con"}, {"content": "Incomplete'
    )
    recovered = _extract_statements_payload(truncated)
    assert len(recovered) == 2
    assert recovered[0]["position"] == "pro"


# ---------------------------------------------------------------------------
# _fallback_seed_statements: deterministic floor with spectrum balance
# ---------------------------------------------------------------------------

def test_fallback_reaches_recommended_floor_with_distinct_balanced_statements():
    out = _fallback_seed_statements(title="Cycle lane expansion", excerpt="Council debate", count=7)

    assert len(out) == 7
    assert len({s["content"] for s in out}) == 7, "fallback statements must be distinct"
    positions = [s["position"] for s in out]
    for stance in ("pro", "con", "neutral"):
        assert stance in positions, f"fallback should span the spectrum ({stance} missing)"


# ---------------------------------------------------------------------------
# generate_seed_statements: guaranteed floor via retry + fallback padding
# ---------------------------------------------------------------------------

def test_generate_pads_to_floor_when_no_api_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out = generate_seed_statements(
        title="Cycle lane expansion in Bristol",
        excerpt="The council is debating new protected lanes.",
        count=7,
    )

    assert len(out) == 7
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_defaults_to_recommended_count(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out = generate_seed_statements(title="A civic topic worth debating")

    assert len(out) == DEFAULT_SEED_COUNT


def test_generate_accumulates_across_providers_openai_first(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")

    def fake_openai(**kwargs):
        return [{"content": f"OpenAI statement {i} that is comfortably long enough.",
                 "position": "pro"} for i in range(3)]

    def fake_anthropic(**kwargs):
        return [{"content": f"Anthropic statement {i} that is comfortably long enough.",
                 "position": "con"} for i in range(5)]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)
    monkeypatch.setattr(seed_generator, "_generate_with_anthropic", fake_anthropic)

    out = generate_seed_statements(title="Topic", count=7)

    assert len(out) == 7
    assert any(s["content"].startswith("OpenAI") for s in out)
    assert any(s["content"].startswith("Anthropic") for s in out), "should top up from Anthropic"
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_skips_anthropic_when_openai_is_sufficient(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    called = {"anthropic": False}

    def fake_openai(**kwargs):
        # Balanced enough that finalize need not inject spectrum from fallback,
        # and long enough that Anthropic is never required for count.
        return [
            {"content": f"Pro statement {i} about the policy trade-off in cities.",
             "position": "pro"} for i in range(3)
        ] + [
            {"content": f"Con statement {i} about the policy trade-off in cities.",
             "position": "con"} for i in range(3)
        ] + [
            {"content": f"Neutral statement {i} about the policy trade-off in cities.",
             "position": "neutral"} for i in range(2)
        ]

    def fake_anthropic(**kwargs):
        called["anthropic"] = True
        return []

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)
    monkeypatch.setattr(seed_generator, "_generate_with_anthropic", fake_anthropic)

    out = generate_seed_statements(title="Topic", count=7)

    assert len(out) == 7
    assert called["anthropic"] is False, "Anthropic must not run once the floor is met"


def test_generate_falls_back_when_providers_stay_short(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fake_openai(**kwargs):
        return [{"content": "The single statement the provider keeps returning here.",
                 "position": "pro"}]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)

    out = generate_seed_statements(title="Topic", excerpt="context", count=7)

    assert len(out) == 7, "must pad with deterministic fallback to reach the floor"
    assert any(s["content"].startswith("The single statement") for s in out)
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_restores_spectrum_when_llm_is_one_sided(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fake_openai(**kwargs):
        return [
            {"content": f"All pro statement number {i} about expanding this policy now.",
             "position": "pro"}
            for i in range(7)
        ]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)

    out = generate_seed_statements(title="One-sided topic", count=7)

    assert len(out) == 7
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_respects_exclude_contents(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    first = generate_seed_statements(title="Exclude test topic", count=3)
    exclude = [s["content"] for s in first]

    second = generate_seed_statements(
        title="Exclude test topic",
        count=3,
        exclude_contents=exclude,
    )

    assert len(second) == 3
    assert not ({s["content"] for s in second} & set(exclude))


def test_generate_requires_topic_or_title():
    with pytest.raises(ValueError):
        generate_seed_statements()


def test_single_source_generator_delegates_to_shared_floor(monkeypatch):
    """Podcast/newsletter path must not bypass the shared floor guarantees."""
    from types import SimpleNamespace
    from app.trending.podcast_publisher import generate_single_source_seed_statements

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    article = SimpleNamespace(
        title="A podcast episode about civic trade-offs",
        summary="Hosts debate whether cities should expand protected cycle lanes.",
        source=SimpleNamespace(name="Example Podcast"),
    )

    out = generate_single_source_seed_statements(article)

    assert len(out) == DEFAULT_SEED_COUNT
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}
