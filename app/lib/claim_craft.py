"""Pol.is-style claim craft: detect text that cannot carry Agree / Disagree / Unsure.

Shared by seed generation and daily-question selection so a hedge that slips
into ``seed_statements`` cannot become tomorrow's stance CTA.
"""

from __future__ import annotations

import re

# Bare "if"/"whether" are NOT here: "If X, Y must Z" and "Whether or not X, Y must Z"
# are valid conditional claims. Real "If…?" questions still end in "?", caught below.
_INTERROGATIVE_OPENER = re.compile(
    r"^(what|who|whom|whose|which|when|where|why|how|"
    r"can|could|would|should|is|are|do|does|did|will|may|might)\b",
    re.IGNORECASE,
)

_NON_CLAIM_OPENER = re.compile(
    r"^(the question of|the issue of|the matter of|"
    r"it (?:is|remains) (?:an open )?question|"
    r"raises (?:the|important) questions?)\b",
    re.IGNORECASE,
)

_WHETHER_OPENER = re.compile(r"^whether\b", re.IGNORECASE)

_WHETHER_HEDGE = re.compile(
    r"^whether\b.+\b("
    r"is (?:a |an |the )?(?:matter|question|issue)(?:\s+for)?\b|"
    r"remains (?:an open question|to be seen)\b|"
    r"is (?:up to|for) (?:governments?|others|them|us)\b"
    r")",
    re.IGNORECASE,
)

# Throat-clearing / meta prompts that never resolve into a voteable consequent.
_META_HEDGE = re.compile(
    r"\b("
    r"we must question\b|"
    r"it is (?:important|crucial) to (?:ask|question|understand)\b|"
    r"understanding (?:the|this) context\b|"
    r"valuable insights\b|"
    r"raises (?:the |important )?questions?\b|"
    r"how can we ensure\b|"
    r"we must (?:evaluate|consider|assess) (?:the|whether)\b"
    r")",
    re.IGNORECASE,
)

# Normative / consequential markers that make Agree/Disagree meaningful.
_NORMATIVE_CLAIM = re.compile(
    r"\b("
    r"should|must|ought to|needs? to|have to|has to|"
    r"cannot|will not|must not|"
    r"(?:is|are) (?:necessary|essential|required|unacceptable|justified|enough|crucial)|"
    r"(?:is|are) (?:the )?(?:best|worst|right|wrong) (?:way|approach|policy|response)\b"
    r")",
    re.IGNORECASE,
)

# Soft modals turn a claim into speculation ("could reduce", "might undermine"),
# which reads as a hypothesis, not a stance. When no normative marker is present,
# their presence blocks the broadened declarative path below.
_SOFT_HEDGE_MODAL = re.compile(
    r"\b(could|might|may|possibly|potentially|perhaps|arguably)\b",
    re.IGNORECASE,
)

# Strong indicative predicates that make a plain declarative contestable without a
# deontic modal: causal/impact verbs, judgement adjectives, and comparatives.
# "Rent controls reduce supply" / "The system is broken" are votable stances even
# though they say neither "should" nor "must". Vague connectors ("lead to",
# "contribute to") are deliberately excluded so speculation stays out.
_ASSERTIVE_PREDICATE = re.compile(
    r"\b("
    # causal / impact verbs (present indicative)
    r"harms?|hurts?|damages?|undermines?|threatens?|weakens?|strengthens?|erodes?|"
    r"reduces?|cuts?|shrinks?|increases?|raises?|lowers?|worsens?|improves?|boosts?|"
    r"drives?|fuels?|causes?|creates?|prevents?|protects?|enables?|forces?|costs?|"
    r"benefits?|destroys?|endangers?|entrenches?|deepens?|widens?|"
    r"discourages?|encourages?|punishes?|rewards?|distorts?|ignores?|silences?|traps?|"
    r"makes?|leaves?|keeps?|"
    # judgement adjectives (predicate)
    r"broken|failing|unfair|unjust|counterproductive|ineffective|unsustainable|"
    r"unworkable|discriminatory|indefensible|reckless|obsolete|inhumane|"
    # comparatives / quantitative judgement
    r"too\s+(?:many|much|high|low|far|slow|fast|weak|strong|expensive|lax|lenient|harsh|big)|"
    r"not\s+enough|worse\s+than|better\s+than"
    r")\b",
    re.IGNORECASE,
)

# Conditional-claim tokens (shared with whether-opener consequent check).
_CLAIM_TOKENS = (
    " should ",
    " must ",
    " because ",
    " ought ",
    " needs to ",
    " cannot ",
    " will ",
    " would ",
)


def is_question_form(content: str) -> bool:
    """
    True when text is an open question or non-claim hedge rather than a votable claim.

    Conditional claims are kept: ``If X, Y must Z`` / ``Whether or not X, Y should Z``.
    Bare whether-hedges without a consequent claim are rejected.
    """
    text = (content or "").strip()
    if not text:
        return False
    if "?" in text:
        return True
    if _NON_CLAIM_OPENER.match(text):
        return True
    if re.search(r"\braises (?:the |important )?questions?\b", text, re.IGNORECASE):
        return True
    if _WHETHER_OPENER.match(text):
        if _WHETHER_HEDGE.match(text):
            return True
        lower = f" {text.lower()} "
        if "," in text and any(token in lower for token in _CLAIM_TOKENS):
            return False
        return True
    return bool(_INTERROGATIVE_OPENER.match(text))


def is_votable_claim(content: str) -> bool:
    """
    True when text is a clear, declarative claim fit for Agree / Disagree / Unsure.

    Rejects open questions, whether-hedges, and throat-clearing meta that never
    lands a claim (the failure mode behind weak brief-sourced daily questions).

    Accepts two shapes of declarative claim:

    1. Normative — a deontic modal or evaluative consequent (``should``, ``must``,
       ``is essential``). This is the dominant form the seed generator produces.
    2. Strong declarative — a causal, judgement, or comparative assertion without a
       modal (``Rent controls reduce supply``, ``The system is broken``,
       ``Immigration is too high``). Speculation softened by ``could`` / ``might`` /
       ``may`` is excluded — a hypothesis is not a stance.
    """
    text = " ".join((content or "").split()).strip()
    if not text or len(text) < 24:
        return False
    if is_question_form(text):
        return False
    if _META_HEDGE.search(text):
        return False
    if _NORMATIVE_CLAIM.search(text):
        return True
    if _SOFT_HEDGE_MODAL.search(text):
        return False
    return bool(_ASSERTIVE_PREDICATE.search(text))
