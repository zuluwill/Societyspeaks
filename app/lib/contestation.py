"""Contestation signal: does this claim have a losing side?

Complements :mod:`app.lib.claim_craft`, which decides whether text is a votable
claim *at all*. The two checks are orthogonal, and conflating them is what
produced the July 2026 participation collapse: "Emergency response plans must be
transparent and involve community input" is a perfectly well-formed votable
claim that nobody disagrees with, so nobody votes.

Grounded in the 20–28 Jul 2026 daily-question corpus:

* The two questions that drew 100+ votes were **globally scoped live events with
  an explicit trade-off** ("diplomatic solutions should be prioritized *over*
  military interventions").
* Every zero-vote question was either a civic pleasantry (transparency,
  community input, awareness, dialogue) or a **national policy proposition**
  aimed at a mostly non-resident list (Dáil sitting hours, Japan's minimum wage,
  German naturalisation rules).

Selection needs form *and* stakes. This module supplies the stakes half.
"""

from __future__ import annotations

import re

# Trade-off connectives: the strongest single signal, because a trade-off has a
# losing side by construction. "X over Y" / "rather than" / "at the expense of"
# is the shape of the highest-participation question in the corpus.
_TRADEOFF = re.compile(
    r"\b("
    r"prioriti[sz]e[ds]?\s+over|"
    r"rather\s+than|"
    r"instead\s+of|"
    r"at\s+the\s+expense\s+of|"
    r"in\s+preference\s+to|"
    r"even\s+(?:if|when|at|though)|"
    r"outweighs?|"
    r"trade[\s-]?offs?"
    r")\b",
    re.IGNORECASE,
)

# Policy verbs with an identifiable loser: someone pays, loses a right, or is
# compelled. Contrast with the consensus vocabulary below, where the subject of
# the sentence is an unopposed good.
_CONTESTED_STAKE = re.compile(
    r"\b("
    # prohibition / compulsion
    r"ban(?:ned|ning|s)?|prohibit(?:ed|ing|s)?|outlaw(?:ed|ing|s)?|"
    r"criminali[sz]e[ds]?|legali[sz]e[ds]?|decriminali[sz]e[ds]?|"
    r"mandatory|compulsory|require[ds]?\s+by\s+law|conscription|"
    r"restrict(?:ed|ing|s|ions?)?|cap(?:ped|ping|s)?|quotas?|rations?|"
    # money moving from someone to someone else
    r"tax(?:ed|ing|es|ation)?|levy|levies|tariffs?|subsid(?:y|ies|ise[ds]?|ize[ds]?)|"
    r"nationali[sz]e[ds]?|privati[sz]e[ds]?|means[\s-]?test(?:ed|ing)?|"
    r"cut(?:s|ting)?|abolish(?:ed|ing|es)?|scrap(?:ped|ping|s)?|defund(?:ed|ing|s)?|"
    r"reparations?|redistribut(?:e[ds]?|ion)|"
    # coercive state action
    r"deport(?:ed|ing|ations?|s)?|expel(?:led|ling|s)?|detain(?:ed|ing|s)?|"
    r"sanction(?:ed|ing|s)?|censor(?:ed|ing|ship|s)?|surveil(?:led|lance|s)?|"
    r"seiz(?:e[ds]?|ing|ures?)|confiscat(?:e[ds]?|ion)|strikes?\s+on|"
    # explicit blame / failure judgements
    r"liability|serious\s+error|has\s+failed|is\s+broken|unjustified"
    r")\b",
    re.IGNORECASE,
)

# Vocabulary of universally-approved goods. A claim built mostly from these has
# no opposing camp: there is no constituency against transparency or dialogue.
# Every zero-vote question in the corpus scores high here.
_CONSENSUS_VALENCE = re.compile(
    r"\b("
    r"transparen(?:t|cy)|accountab(?:le|ility)|community\s+input|"
    r"public\s+trust|stakeholders?|engagement|empower(?:ed|ing|ment|s)?|"
    r"inclusiv(?:e|ity)|dialogue|collaborat(?:e|ion|ive)|cooperation|"
    r"awareness|resilience|best\s+practices?|capacity\s+building|"
    r"coordination|meaningful|holistic|comprehensive|"
    r"should\s+be\s+(?:considered|assessed|evaluated|explored|examined)|"
    r"taken\s+into\s+account|tailored\s+to|"
    r"quality\s+(?:care|services?|education)|"
    r"sustainab(?:le|ility)|effective\s+(?:policies|policy|interventions?)"
    r")\b",
    re.IGNORECASE,
)

# ---------------------------------------------------------------------------
# Jurisdiction scope
#
# Naming a country is NOT enough to mark a claim as national — the highest-
# scoring question in the corpus ("The US strikes on Iran…") names two. What
# marks a claim as national is a country *plus* a domestic-policy subject: the
# reader must live there for the question to mean anything.
# ---------------------------------------------------------------------------

_COUNTRY_OR_DEMONYM = re.compile(
    r"\b("
    r"german(?:y|s)?|french|france|irish|ireland|japan(?:ese)?|dutch|netherlands|"
    r"canad(?:a|ian)|singapore(?:an)?|australian?|italian?|italy|spanish|spain|"
    r"polish|poland|swedish|sweden|norwegian|norway|danish|denmark|finnish|finland|"
    r"belgian|belgium|austrian?|swiss|switzerland|portuguese|portugal|greek|greece|"
    r"scottish|scotland|welsh|wales|english|england|british|britain|"
    r"korean?|indian?|brazil(?:ian)?|mexican?|mexico|argentin(?:a|e|ian)"
    r")\b",
    re.IGNORECASE,
)

# National institutions: naming one presupposes local civic knowledge.
_NATIONAL_INSTITUTION = re.compile(
    r"\b("
    r"d[aá]il|oireachtas|teachta|tds|bundestag|bundesrat|knesset|riksdag|"
    r"folketing|storting|eduskunta|sejm|cortes|assembl[ée]e\s+nationale|"
    r"house\s+of\s+(?:commons|lords)|holyrood|senedd|st[oø]rting|"
    r"nhs|medicare|medicaid|hse|bafin|ofsted|ofcom|"
    r"basic\s+law|grundgesetz|article\s+21"
    r")\b",
    re.IGNORECASE,
)

# Domestic-policy subjects: only actionable for residents.
_DOMESTIC_POLICY = re.compile(
    r"\b("
    r"naturalisation|naturalization|citizenship\s+requirements?|"
    r"minimum\s+wage|zoning|planning\s+permission|"
    r"curriculum|school\s+funding|university\s+fees|tuition\s+fees|"
    r"sitting\s+hours|constituenc(?:y|ies)|devolution|"
    r"corporate\s+tax|income\s+tax|council\s+tax|vat\b|tax\s+base|"
    r"pensions?|social\s+care|elderly\s+care|palliative\s+care|"
    r"health\s+insurance|healthcare\s+system|hospital\s+system|"
    r"asylum\s+capacity|insulat(?:e|ion)|housing\s+supply|"
    r"defence\s+spending|gdp\s+defence|voting\s+age"
    r")\b",
    re.IGNORECASE,
)

# Outlet-attribution boilerplate stripped before comparing left/right framings,
# so "Left-leaning outlets emphasise" vs "Right-leaning outlets highlight" does
# not register as substantive divergence.
_OUTLET_BOILERPLATE = re.compile(
    r"^\s*(?:left|right|centre|center)[\s-]*(?:leaning|wing)?\s*"
    r"(?:outlets?|media|press|sources?|commentators?)?\s*"
    r"(?:tend\s+to\s+)?"
    r"(?:emphasi[sz]e|highlight|focus\s+on|stress|argue|frame|note|report|"
    r"portray|present|characteri[sz]e)?\s*(?:that\s+)?",
    re.IGNORECASE,
)

_STOPWORDS = frozenset(
    """a an the and or but of to in on for with as at by from is are was were be
    been being that this these those it its their there has have had will would
    should could may might more most than then so such other others""".split()
)

# A leaning counts as engaged when it holds a material share of coverage.
MATERIAL_COVERAGE_SHARE = 0.10


def _content_tokens(text: str) -> set[str]:
    """Lowercase, de-stopworded word set used for framing comparison."""
    words = re.findall(r"[a-z]{3,}", (text or "").lower())
    return {w for w in words if w not in _STOPWORDS}


def _strip_outlet_boilerplate(text) -> str:
    if not isinstance(text, str):
        return ""
    return _OUTLET_BOILERPLATE.sub("", text.strip(), count=1).strip()


def perspective_divergence(perspectives) -> float | None:
    """
    How differently do left and right outlets frame this story? 0.0–1.0.

    Returns ``None`` when the brief item carries no usable left/right pair —
    true for roughly 80% of items, so callers must degrade to coverage signals
    rather than treating absence as low divergence.
    """
    if not isinstance(perspectives, dict):
        return None
    left = _strip_outlet_boilerplate(perspectives.get('left'))
    right = _strip_outlet_boilerplate(perspectives.get('right'))
    if not left or not right:
        return None

    left_tokens = _content_tokens(left)
    right_tokens = _content_tokens(right)
    if not left_tokens or not right_tokens:
        return None

    union = left_tokens | right_tokens
    if not union:
        return None
    similarity = len(left_tokens & right_tokens) / len(union)
    return round(1.0 - similarity, 4)


def coverage_engagement(coverage_distribution) -> int:
    """
    Count political leanings holding a material share of coverage (0–3).

    Three engaged leanings means left, centre and right are all arguing about
    the story. One means a single bloc covered it and the others ignored it —
    the dominant signature of zero-vote questions in the corpus.
    """
    if not isinstance(coverage_distribution, dict):
        return 0
    engaged = 0
    for leaning in ('left', 'center', 'right'):
        try:
            share = float(coverage_distribution.get(leaning) or 0)
        except (TypeError, ValueError):
            share = 0.0
        if share >= MATERIAL_COVERAGE_SHARE:
            engaged += 1
    return engaged


def is_national_scope(text: str) -> bool:
    """
    True when a claim needs local residency or civic knowledge to hold a view.

    Naming a country is not sufficient — international events name countries as
    actors. National scope requires a national institution, or a country paired
    with a domestic-policy subject.
    """
    content = " ".join((text or "").split())
    if not content:
        return False
    if _NATIONAL_INSTITUTION.search(content):
        return True
    return bool(
        _COUNTRY_OR_DEMONYM.search(content) and _DOMESTIC_POLICY.search(content)
    )


def consensus_pleasantry_ratio(text: str) -> float:
    """Density of unopposed-good vocabulary, normalised to 0.0–1.0."""
    content = " ".join((text or "").split())
    if not content:
        return 0.0
    hits = len(_CONSENSUS_VALENCE.findall(content))
    if not hits:
        return 0.0
    # Three or more consensus markers is a pleasantry regardless of length.
    return min(hits / 3.0, 1.0)


def contestation_score(text: str, perspectives=None) -> float:
    """
    Probability-ish 0.0–1.0 estimate that a claim has a real opposing camp.

    Replaces the previous modal-verb heuristic, which counted ``should`` /
    ``must`` / ``require`` and therefore scored civic pleasantries as maximally
    controversial — they are all phrased prescriptively.

    ``perspectives`` is the optional ``BriefItem.perspectives`` payload; when it
    carries both a left and a right framing, their divergence is folded in.
    """
    content = " ".join((text or "").split())
    if not content:
        return 0.0

    score = 0.35  # neutral prior for a well-formed claim

    if _TRADEOFF.search(content):
        score += 0.30

    stake_hits = len(set(m.lower() for m in _CONTESTED_STAKE.findall(content)))
    score += min(stake_hits, 3) * 0.10

    score -= consensus_pleasantry_ratio(content) * 0.35

    if is_national_scope(content):
        score -= 0.25

    divergence = perspective_divergence(perspectives)
    if divergence is not None:
        # Centred on 0.5: genuinely different framings add, near-identical
        # framings subtract. Absence of data is neutral, handled above.
        score += (divergence - 0.5) * 0.20

    return round(max(0.0, min(1.0, score)), 4)
