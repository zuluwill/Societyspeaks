"""Tests for shared Pol.is-style claim craft (seed gen + daily question)."""

import pytest

from app.lib.claim_craft import is_question_form, is_votable_claim


@pytest.mark.parametrize("text,expected", [
    ("NATO should prioritise democratic values among member states.", False),
    ("Can NATO effectively balance traditional defence roles with new challenges?", True),
    ("Whether NATO expands further is a matter for member states.", True),
    ("If the council raises fees, local services must measurably improve.", False),
    ("Whether or not spending rises, the government must publish defence outcomes.", False),
])
def test_is_question_form_parity(text, expected):
    assert is_question_form(text) is expected


@pytest.mark.parametrize("text,expected", [
    (
        "European governments should expand legal asylum capacity rather than "
        "relying on deterrence alone.",
        True,
    ),
    (
        "Community outreach initiatives that connect veterans with local support "
        "networks are essential.",
        True,
    ),
    (
        "While updated data can provide valuable insights, we must question what "
        "factors influence these statistics. Are they reflecting actual needs?",
        False,
    ),
    (
        "Support programs for veterans could lead to a drain on public resources.",
        False,  # soft "could" with no normative consequent
    ),
    (
        "How can updated data on migration help us make better policies?",
        False,
    ),
    ("", False),
    ("Too short", False),
])
def test_is_votable_claim_rejects_hedges_and_soft_fillers(text, expected):
    assert is_votable_claim(text) is expected


@pytest.mark.parametrize("text", [
    # Strong declarative claims with no deontic modal — still votable stances.
    "Rent controls reduce the supply of affordable housing.",
    "Social media harms teenagers' mental health.",
    "Remote work makes distributed teams less productive.",
    "Current immigration levels are too high for public services to absorb.",
    "The asylum system is fundamentally broken.",
    "Deterrence-only border policy is counterproductive.",
    "Means-testing benefits traps families in poverty.",
])
def test_is_votable_claim_accepts_strong_declaratives_without_modals(text):
    assert is_votable_claim(text) is True


@pytest.mark.parametrize("text", [
    # Speculation, not a stance: soft modal + no normative consequent.
    "Support programs for veterans could lead to a drain on public resources.",
    "Migration might increase pressure on frontline services.",
    "New tariffs may reduce domestic manufacturing output over time.",
    "Automation could possibly worsen regional inequality.",
])
def test_is_votable_claim_rejects_soft_modal_speculation(text):
    assert is_votable_claim(text) is False
