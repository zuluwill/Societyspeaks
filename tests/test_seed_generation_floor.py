"""
Behavioural tests for the seed-statement floor and Pol.is-style craft guarantees.
"""

import json

import pytest

from app.discussions.thresholds import CONSENSUS_RECOMMENDED_STATEMENT_COUNT
from app.trending import seed_generator
from app.trending.seed_generator import (
    DEFAULT_SEED_COUNT,
    _ParseStats,
    _build_prompt,
    _claim_quality_sort_key,
    _extract_statements_payload,
    _fallback_seed_statements,
    _generation_shortfall,
    _is_near_duplicate,
    _is_question_form,
    _looks_compound_idea,
    _min_bridge_count,
    _parse_and_validate_statements,
    _select_balanced,
    generate_seed_statements,
)


def test_default_seed_count_matches_consensus_threshold():
    assert DEFAULT_SEED_COUNT == CONSENSUS_RECOMMENDED_STATEMENT_COUNT == 10


def test_prompt_includes_few_shot_and_atomicity_guidance():
    prompt = _build_prompt(
        topic=None,
        title="NATO's future",
        excerpt="Alliance debate",
        source_name=None,
        count=10,
    )
    assert "Can NATO balance old and new roles" in prompt
    assert "ensuring collective defence" in prompt
    assert "intent" in prompt
    assert "bridge" in prompt
    assert "ONE idea only" in prompt


def test_prompt_targeted_retry_requests_missing_stances():
    from app.trending.seed_generator import _GenerationFocus

    focus = _GenerationFocus(
        request_count=4,
        focus_positions=("con", "neutral"),
        need_bridge=2,
    )
    prompt = _build_prompt(
        topic=None,
        title="NATO's future",
        excerpt=None,
        source_name=None,
        count=4,
        focus=focus,
    )
    assert "PRIORITY THIS ROUND" in prompt
    assert "con" in prompt and "neutral" in prompt
    assert "bridge" in prompt.lower()


# ---------------------------------------------------------------------------
# Question / hedge / compound craft
# ---------------------------------------------------------------------------

def test_parse_keeps_statements_that_fail_the_specificity_gate():
    """Non-specific but valid claims must survive (the 1-statement bug)."""
    payload = json.dumps([
        {"content": "Local councils should expand cycle lanes because congestion harms residents.",
         "position": "pro"},
        {"content": "Cars remain the most practical option for many rural families today.",
         "position": "con"},
        {"content": "Cycle-lane impacts on small high-street traders deserve careful measurement.",
         "position": "neutral"},
    ])

    result = _parse_and_validate_statements(payload, count=DEFAULT_SEED_COUNT)

    assert len(result) == 3, "valid claims must not be dropped by the soft gate"
    contents = {r["content"] for r in result}
    assert any("Cars remain" in c for c in contents)
    assert any("high-street traders" in c for c in contents)


def test_parse_rejects_question_form_statements():
    """Open questions break Agree/Disagree/Unsure and must never enter the seed set."""
    payload = json.dumps([
        {"content": "Local councils should expand cycle lanes because congestion harms residents.",
         "position": "pro"},
        {"content": "Can NATO balance traditional defence roles with emerging global challenges?",
         "position": "neutral"},
        {"content": "What measurable outcomes should define success for this policy?",
         "position": "neutral"},
        {
            "content": (
                "The conversation surrounding NATO's future raises important questions "
                "about its adaptability. Can NATO effectively balance traditional defense "
                "roles with emerging global challenges, or will this lead to divisions?"
            ),
            "position": "neutral",
        },
        {"content": "NATO should prioritise collective defence over expanding into new global roles.",
         "position": "con"},
    ])
    stats = _ParseStats()
    result = _parse_and_validate_statements(payload, count=DEFAULT_SEED_COUNT, stats=stats)

    assert len(result) == 2
    assert stats.dropped_question >= 3
    assert stats.kept == 2
    contents = {r["content"] for r in result}
    assert any("Local councils should" in c for c in contents)
    assert any("NATO should prioritise" in c for c in contents)
    assert all(not _is_question_form(c) for c in contents)


@pytest.mark.parametrize("text,expected", [
    ("NATO should prioritise democratic values among member states.", False),
    ("Can NATO effectively balance traditional defence roles with new challenges?", True),
    ("What evidence would change your mind about this approach?", True),
    ("Who should be accountable for these decisions?", True),
    ("Should governments expand cycle lanes in major cities?", True),
    ("Whether NATO expands further is a matter for member states.", True),
    ("Whether defence spending rises is a matter for governments.", True),
    ("Whether the policy works remains to be seen.", True),
    ("The question of defence spending deserves closer scrutiny from voters.", True),
    # Conditional claims — votable middle-ground content, must NOT be rejected.
    ("If the council raises fees, local services must measurably improve.", False),
    ("Whether or not spending rises, the government must publish defence outcomes.", False),
])
def test_is_question_form_detects_open_questions_and_hedges(text, expected):
    assert _is_question_form(text) is expected


def test_parse_keeps_conditional_claims_and_stats_match_returned_slice():
    """Oversampled valid sets must not inflate kept/drop metrics via slicing."""
    payload = json.dumps([
        {"content": "If the council raises fees, local services must measurably improve.",
         "position": "neutral", "intent": "bridge"},
        {"content": "Whether or not spending rises, the government must publish defence outcomes.",
         "position": "neutral", "intent": "bridge"},
        {"content": "Cities should expand protected cycle lanes on arterial roads.",
         "position": "pro", "intent": "divisive"},
        {"content": "Congestion charges unfairly punish low-income suburban workers.",
         "position": "con", "intent": "divisive"},
        {"content": "Transport schemes should publish clear success metrics before expansion.",
         "position": "neutral", "intent": "bridge"},
    ])
    stats = _ParseStats()
    result = _parse_and_validate_statements(payload, count=3, stats=stats)

    assert len(result) == 3
    assert stats.kept == 3, "kept must equal returned length, not pre-slice validated count"
    assert stats.dropped_question == 0
    assert any(r["content"].startswith("If the council") for r in result)


@pytest.mark.parametrize("text,expected", [
    ("NATO should prioritise collective defence over new global roles.", False),
    (
        "We need opioid treatment as a health emergency. Doctors who overprescribe "
        "should be imprisoned instead of addicts.",
        True,
    ),
    ("Councils should expand cycle lanes and also ban cars from every high street.", True),
    (
        "NATO's future should prioritize the democratic values of its member states, "
        "ensuring that shifts in focus do not compromise collective defense.",
        True,
    ),
])
def test_looks_compound_idea_flags_multi_claim_statements(text, expected):
    assert _looks_compound_idea(text) is expected


def test_quality_rank_prefers_single_idea_over_compound_without_dropping_either():
    sharp = "NATO should prioritise collective defence over expanding into new global roles."
    compound = (
        "NATO should prioritise collective defence. Member states must also cut "
        "defence budgets because diplomacy alone can keep the peace."
    )
    assert _claim_quality_sort_key(sharp) < _claim_quality_sort_key(compound)
    assert not _is_question_form(sharp)
    assert not _is_question_form(compound)


def test_quality_rank_does_not_punish_needed_length_harder_than_padding():
    concise = "Britain should rejoin the EU customs union within five years."
    longer_forceful = (
        "Britain should rejoin the EU customs union within five years because "
        "Northern Ireland trade friction is already damaging manufacturers."
    )
    padded = (
        "When one carefully considers the broader geopolitical and economic landscape "
        "facing the United Kingdom in the coming decade, it becomes increasingly clear "
        "that Britain should eventually rejoin the EU customs union within five years "
        "after an appropriate period of reflection and consultation with stakeholders."
    )
    assert _claim_quality_sort_key(concise) < _claim_quality_sort_key(padded)
    assert _claim_quality_sort_key(longer_forceful) < _claim_quality_sort_key(padded)


def test_parse_deduplicates_repeated_content():
    payload = json.dumps([
        {"content": "Councils should invest in safer junctions because collisions are rising.",
         "position": "pro"},
        {"content": "Councils should invest in safer junctions because collisions are rising.",
         "position": "pro"},
    ])
    stats = _ParseStats()
    result = _parse_and_validate_statements(payload, count=DEFAULT_SEED_COUNT, stats=stats)

    assert len(result) == 1
    assert stats.dropped_dupe == 1


def test_parse_drops_near_duplicate_paraphrases():
    payload = json.dumps([
        {"content": "NATO must increase spending on cyber defence across member states.",
         "position": "pro", "intent": "divisive"},
        {"content": "NATO should increase spending on cyber defence across member states.",
         "position": "pro", "intent": "divisive"},
        {"content": "European states should cut NATO budgets and rely on diplomacy alone.",
         "position": "con", "intent": "divisive"},
    ])
    stats = _ParseStats()
    result = _parse_and_validate_statements(payload, count=DEFAULT_SEED_COUNT, stats=stats)

    assert len(result) == 2
    assert stats.dropped_near_dupe == 1
    assert not _is_near_duplicate(
        "European states should cut NATO budgets and rely on diplomacy alone.",
        ["NATO must increase spending on cyber defence across member states."],
    )


def test_parse_trims_to_requested_count():
    subjects = [
        "cycle lanes", "congestion charges", "school streets", "low-traffic neighbourhoods",
        "bus priority corridors", "tram extensions", "park-and-ride hubs", "clean-air zones",
        "pavement parking bans", "shared e-scooter fleets", "river crossings", "night buses",
        "freight consolidation hubs", "workplace parking levies",
    ]
    payload = json.dumps([
        {"content": f"Cities should fund {subject} because evidence shows clear public benefit.",
         "position": "pro"}
        for subject in subjects
    ])

    result = _parse_and_validate_statements(payload, count=DEFAULT_SEED_COUNT)

    assert len(result) == DEFAULT_SEED_COUNT


def test_extract_recovers_complete_objects_from_truncated_json():
    truncated = (
        '[{"content": "Councils should expand cycle lanes because congestion is rising.", '
        '"position": "pro"}, {"content": "Rural families still rely on cars every day.", '
        '"position": "con"}, {"content": "Incomplete'
    )
    recovered = _extract_statements_payload(truncated)
    assert len(recovered) == 2
    assert recovered[0]["position"] == "pro"


def test_parse_preserves_bridge_intent():
    payload = json.dumps([
        {"content": "Public decisions on housing should publish clear success metrics first.",
         "position": "neutral", "intent": "bridge"},
        {"content": "Councils should ban all private cars from city centres immediately.",
         "position": "pro", "intent": "divisive"},
    ])
    result = _parse_and_validate_statements(payload, count=5)
    by_content = {r["content"]: r for r in result}
    assert by_content[
        "Public decisions on housing should publish clear success metrics first."
    ]["intent"] == "bridge"


# ---------------------------------------------------------------------------
# Shortfall / selection / fallback
# ---------------------------------------------------------------------------

def test_generation_shortfall_requests_missing_stances_even_when_count_met():
    collected = [
        {"content": f"Pro claim {i} about expanding this policy now.", "position": "pro",
         "intent": "divisive"}
        for i in range(10)
    ]
    shortfall = _generation_shortfall(collected, count=10)
    assert shortfall is not None
    assert "con" in shortfall.focus_positions
    assert "neutral" in shortfall.focus_positions


def test_generation_shortfall_requests_bridge_coverage():
    collected = [
        {"content": "Pro claim about expanding this policy in cities now.", "position": "pro",
         "intent": "divisive"},
        {"content": "Con claim about expanding this policy in cities now.", "position": "con",
         "intent": "divisive"},
        {"content": "Another pro claim about expanding this policy in cities.", "position": "pro",
         "intent": "divisive"},
        {"content": "Another con claim about expanding this policy in cities.", "position": "con",
         "intent": "divisive"},
        {"content": "Third pro claim about expanding this policy in cities.", "position": "pro",
         "intent": "divisive"},
        {"content": "Neutral but still divisive framing of the city policy.", "position": "neutral",
         "intent": "divisive"},
    ]
    # Pad to count with more divisive
    while len(collected) < 10:
        collected.append({
            "content": f"Extra divisive claim number {len(collected)} on city policy.",
            "position": "pro",
            "intent": "divisive",
        })
    shortfall = _generation_shortfall(collected, count=10)
    assert shortfall is not None
    assert shortfall.need_bridge >= 1


def test_min_bridge_count_scales_with_set_size():
    assert _min_bridge_count(2) == 0
    assert _min_bridge_count(5) == 1
    assert _min_bridge_count(10) == 2


def test_select_balanced_guarantees_bridge_and_spectrum():
    statements = [
        {"content": f"Pro divisive claim number {i} on the policy.", "position": "pro",
         "intent": "divisive"}
        for i in range(6)
    ] + [
        {"content": f"Con divisive claim number {i} on the policy.", "position": "con",
         "intent": "divisive"}
        for i in range(4)
    ] + [
        {"content": "Shared facts should ground debate before partisan talking points.",
         "position": "neutral", "intent": "bridge"},
        {"content": "Leaders should be accountable for trade-offs they accept publicly.",
         "position": "neutral", "intent": "bridge"},
    ]
    out = _select_balanced(statements, count=10)
    assert len(out) == 10
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}
    # Public finalize strips intent; select_balanced still returns it internally.
    assert sum(1 for s in out if s.get("intent") == "bridge") >= 2


def test_fallback_reaches_recommended_floor_with_distinct_balanced_statements():
    out = _fallback_seed_statements(
        title="Cycle lane expansion", excerpt="Council debate", count=DEFAULT_SEED_COUNT
    )

    assert len(out) == DEFAULT_SEED_COUNT
    assert len({s["content"] for s in out}) == DEFAULT_SEED_COUNT
    positions = [s["position"] for s in out]
    for stance in ("pro", "con", "neutral"):
        assert stance in positions
    assert all(not _is_question_form(s["content"]) for s in out)
    assert all(not _looks_compound_idea(s["content"]) for s in out)
    assert all("Context:" not in s["content"] for s in out)
    assert sum(1 for s in out if s["intent"] == "bridge") >= _min_bridge_count(DEFAULT_SEED_COUNT)


# ---------------------------------------------------------------------------
# generate_seed_statements integration
# ---------------------------------------------------------------------------

def test_generate_pads_to_floor_when_no_api_keys(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    out = generate_seed_statements(
        title="Cycle lane expansion in Bristol",
        excerpt="The council is debating new protected lanes.",
        count=DEFAULT_SEED_COUNT,
    )

    assert len(out) == DEFAULT_SEED_COUNT
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
        return [
            {"content": "OpenAI says cities should expand protected cycle lanes now.",
             "position": "pro", "intent": "divisive"},
            {"content": "OpenAI says congestion charging should cover the urban core.",
             "position": "pro", "intent": "divisive"},
            {"content": "OpenAI says school streets should ban through-traffic at pick-up.",
             "position": "pro", "intent": "divisive"},
        ]

    def fake_anthropic(**kwargs):
        return [
            {"content": "Anthropic says congestion charges punish suburban workers unfairly.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says cycle lanes harm traders without cutting emissions.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says school street bans displace traffic onto side roads.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says tram schemes lock cities into avoidable capital costs.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says freight hubs should replace kerbside loading first.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says workplace parking levies should be delayed indefinitely.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says night-bus cuts prove demand was never there.",
             "position": "con", "intent": "divisive"},
            {"content": "Anthropic says shared scooters should be banned from pavements entirely.",
             "position": "con", "intent": "divisive"},
        ]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)
    monkeypatch.setattr(seed_generator, "_generate_with_anthropic", fake_anthropic)

    out = generate_seed_statements(title="Topic", count=DEFAULT_SEED_COUNT)

    assert len(out) == DEFAULT_SEED_COUNT
    assert any(s["content"].startswith("OpenAI") for s in out)
    assert any(s["content"].startswith("Anthropic") for s in out)
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_skips_anthropic_when_openai_is_sufficient(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "y")
    called = {"anthropic": False}

    def fake_openai(**kwargs):
        pro = [
            "Cities should expand protected cycle lanes on arterial roads.",
            "Councils must introduce congestion charges in the urban core.",
            "School streets should ban through-traffic at pick-up times.",
            "Tram extensions should be prioritised over new urban motorways.",
        ]
        con = [
            "Congestion charges unfairly punish low-income suburban workers.",
            "Protected cycle lanes harm high-street traders without cutting emissions.",
            "School street bans displace traffic onto neighbouring residential roads.",
            "Tram schemes lock cities into costs that buses could meet more flexibly.",
        ]
        bridge = [
            "Transport schemes should publish clear success metrics before expansion.",
            "Affected residents should have a binding say before major street changes.",
            "Debate on urban transport should start from shared safety and air-quality data.",
        ]
        return (
            [{"content": c, "position": "pro", "intent": "divisive"} for c in pro]
            + [{"content": c, "position": "con", "intent": "divisive"} for c in con]
            + [{"content": c, "position": "neutral", "intent": "bridge"} for c in bridge]
        )

    def fake_anthropic(**kwargs):
        called["anthropic"] = True
        return []

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)
    monkeypatch.setattr(seed_generator, "_generate_with_anthropic", fake_anthropic)

    out = generate_seed_statements(title="Topic", count=DEFAULT_SEED_COUNT)

    assert len(out) == DEFAULT_SEED_COUNT
    assert called["anthropic"] is False, "Anthropic must not run once quality targets are met"


def test_generate_targeted_retry_passes_missing_stances(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    calls = []

    def fake_openai(**kwargs):
        calls.append(kwargs.get("focus"))
        if len(calls) == 1:
            pro_claims = [
                "Cities should expand protected cycle lanes on every arterial road.",
                "Councils must introduce congestion charges across the urban core.",
                "School streets should ban through-traffic during pick-up windows.",
                "Tram extensions should outrank new urban motorway spending.",
                "Clean-air zones should tighten diesel restrictions again next year.",
                "Park-and-ride hubs should be free for all weekday commuters.",
                "Freight consolidation hubs should replace kerbside loading bays.",
                "Workplace parking levies should fund local bus frequency guarantees.",
                "Shared e-scooter fleets should be licensed only on protected lanes.",
                "Night buses should run every fifteen minutes on trunk corridors.",
            ]
            return [
                {"content": c, "position": "pro", "intent": "divisive"}
                for c in pro_claims
            ]
        # Targeted retry should ask for non-pro stances.
        focus = kwargs.get("focus")
        assert focus is not None
        assert focus.focus_positions
        assert "pro" not in focus.focus_positions or "con" in focus.focus_positions
        return [
            {"content": "Opposition should block this policy until evidence improves clearly.",
             "position": "con", "intent": "divisive"},
            {"content": "Shared metrics should define success before expanding this policy.",
             "position": "neutral", "intent": "bridge"},
            {"content": "Trade-offs on this policy should be published for public scrutiny.",
             "position": "neutral", "intent": "bridge"},
        ]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)

    out = generate_seed_statements(title="One-sided topic", count=DEFAULT_SEED_COUNT)

    assert len(calls) >= 2, "lopsided first pass must trigger a targeted retry"
    assert len(out) == DEFAULT_SEED_COUNT
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_falls_back_when_providers_stay_short(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fake_openai(**kwargs):
        return [{"content": "The single statement the provider keeps returning here.",
                 "position": "pro", "intent": "divisive"}]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)

    out = generate_seed_statements(
        title="Topic", excerpt="context", count=DEFAULT_SEED_COUNT
    )

    assert len(out) == DEFAULT_SEED_COUNT
    assert any(s["content"].startswith("The single statement") for s in out)
    assert {"pro", "con", "neutral"} <= {s["position"] for s in out}


def test_generate_restores_spectrum_when_llm_is_one_sided(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    def fake_openai(**kwargs):
        pro_claims = [
            "Cities should expand protected cycle lanes on every arterial road.",
            "Councils must introduce congestion charges across the urban core.",
            "School streets should ban through-traffic during pick-up windows.",
            "Tram extensions should outrank new urban motorway spending.",
            "Clean-air zones should tighten diesel restrictions again next year.",
            "Park-and-ride hubs should be free for all weekday commuters.",
            "Freight consolidation hubs should replace kerbside loading bays.",
            "Workplace parking levies should fund local bus frequency guarantees.",
            "Shared e-scooter fleets should be licensed only on protected lanes.",
            "Night buses should run every fifteen minutes on trunk corridors.",
        ]
        return [{"content": c, "position": "pro", "intent": "divisive"} for c in pro_claims]

    monkeypatch.setattr(seed_generator, "_generate_with_openai", fake_openai)

    out = generate_seed_statements(title="One-sided topic", count=DEFAULT_SEED_COUNT)

    assert len(out) == DEFAULT_SEED_COUNT
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
