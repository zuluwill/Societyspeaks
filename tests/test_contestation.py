"""
Contestation signal tests, anchored on the real 20-28 Jul 2026 corpus.

The regression these guard: a scorer that measures prescriptive grammar
("should", "must", "require") ranks civic pleasantries as maximally
controversial, because pleasantries are phrased prescriptively. Participation
data is unambiguous — the two questions phrased as trade-offs on globally
covered stories drew 178 and 127 votes; every pleasantry and every national
policy proposition drew 0-2.
"""

import pytest

from app.lib.claim_craft import is_votable_claim
from app.lib.contestation import (
    consensus_pleasantry_ratio,
    contestation_score,
    coverage_engagement,
    is_national_scope,
    perspective_divergence,
)

# Verbatim from daily_question, with observed vote counts.
DREW_VOTES = [
    ("Investments in diplomatic solutions should be prioritized over military "
     "interventions to resolve the conflict.", 178),
    ("The US strikes on Iran must be accompanied by a clear strategy for "
     "achieving peace to be justified.", 127),
]

DREW_NOTHING = [
    "Emergency response plans must be transparent and involve community input to gain public trust.",
    "Access to updated data should be made transparent and available to all community members.",
    "Local communities should be empowered to lead hunger reduction initiatives tailored to their needs.",
    "The international community should engage China in dialogue about its military changes.",
]

NATIONAL_POLICY = [
    "Germany should make naturalisation easier and faster — current citizenship requirements are too strict.",
    "Dáil sitting hours should be extended and reformed so TDs spend more time scrutinising legislation.",
    "Japan's minimum wage should be raised to ¥1,500 per hour nationally.",
    "French households should face binding requirements to insulate their homes.",
    "Ireland must begin reducing its reliance on corporate tax revenues by broadening the tax base.",
]


class TestCorpusSeparation:
    @pytest.mark.parametrize("text,votes", DREW_VOTES)
    def test_high_participation_questions_score_above_floor(self, text, votes):
        from app.daily.auto_selection import MIN_BRIEF_CONTESTATION

        assert contestation_score(text) >= MIN_BRIEF_CONTESTATION

    @pytest.mark.parametrize("text", DREW_NOTHING)
    def test_pleasantries_score_below_every_winner(self, text):
        worst_winner = min(contestation_score(t) for t, _ in DREW_VOTES)
        assert contestation_score(text) < worst_winner

    @pytest.mark.parametrize("text", NATIONAL_POLICY)
    def test_national_policy_scores_below_every_winner(self, text):
        worst_winner = min(contestation_score(t) for t, _ in DREW_VOTES)
        assert contestation_score(text) < worst_winner

    @pytest.mark.parametrize("text", DREW_NOTHING + NATIONAL_POLICY)
    def test_losers_are_still_well_formed_claims(self, text):
        """
        The point of the module: these pass claim_craft cleanly. Form was never
        the problem, so a form check could never have caught them.
        """
        assert is_votable_claim(text)


class TestJurisdictionScope:
    @pytest.mark.parametrize("text", NATIONAL_POLICY)
    def test_domestic_policy_is_national(self, text):
        assert is_national_scope(text) is True

    @pytest.mark.parametrize("text,_votes", DREW_VOTES)
    def test_international_events_naming_countries_stay_global(self, text, _votes):
        """Naming a country is not enough — the 127-vote question names two."""
        assert is_national_scope(text) is False

    def test_national_institution_alone_is_enough(self):
        assert is_national_scope("The Bundestag should sit for longer sessions.") is True


class TestPleasantryDetection:
    def test_stacked_consensus_vocabulary_saturates(self):
        text = ("Emergency response plans must be transparent and involve community "
                "input to gain public trust through meaningful dialogue.")
        assert consensus_pleasantry_ratio(text) == 1.0

    def test_contested_claim_has_no_pleasantry_signal(self):
        assert consensus_pleasantry_ratio(
            "Immigration should be capped and enforcement expanded."
        ) == 0.0


class TestCoverageEngagement:
    def test_all_three_leanings_engaged(self):
        assert coverage_engagement({'left': 0.25, 'center': 0.25, 'right': 0.5}) == 3

    def test_single_bloc_coverage(self):
        assert coverage_engagement({'left': 0.0, 'center': 1.0, 'right': 0.0}) == 1

    def test_shares_below_material_threshold_do_not_count(self):
        assert coverage_engagement({'left': 0.02, 'center': 0.96, 'right': 0.02}) == 1

    @pytest.mark.parametrize("payload", [None, {}, "null", [], {'left': 'x'}])
    def test_malformed_payloads_degrade_to_zero(self, payload):
        assert coverage_engagement(payload) == 0


class TestPerspectiveDivergence:
    def test_absent_pair_returns_none_not_zero(self):
        """
        ~80% of brief items carry perspectives=null. Absence must be neutral,
        never "these framings agree".
        """
        assert perspective_divergence(None) is None
        assert perspective_divergence({'center': 'Only the centre covered it.'}) is None
        assert perspective_divergence({'left': 'x', 'right': None}) is None

    def test_outlet_boilerplate_is_not_counted_as_agreement(self):
        divergence = perspective_divergence({
            'left': 'Left-leaning outlets emphasise workers losing bargaining power.',
            'right': 'Right-leaning outlets highlight employers facing higher costs.',
        })
        assert divergence is not None
        assert divergence > 0.8

    def test_identical_framing_scores_near_zero(self):
        divergence = perspective_divergence({
            'left': 'Left-leaning outlets emphasise the need for increased food aid.',
            'right': 'Right-leaning outlets emphasise the need for increased food aid.',
        })
        assert divergence == pytest.approx(0.0, abs=0.05)

    def test_divergence_lifts_an_otherwise_equal_claim(self):
        text = "Tariffs on imported goods should be raised."
        split = contestation_score(text, perspectives={
            'left': 'Left-leaning outlets emphasise consumer prices rising for poorer households.',
            'right': 'Right-leaning outlets highlight domestic manufacturers regaining market share.',
        })
        agreed = contestation_score(text, perspectives={
            'left': 'Left-leaning outlets emphasise the need for careful review.',
            'right': 'Right-leaning outlets emphasise the need for careful review.',
        })
        assert split > agreed


class TestScoreBounds:
    @pytest.mark.parametrize("text", ["", None, "   "])
    def test_empty_input_is_zero_not_a_crash(self, text):
        assert contestation_score(text) == 0.0

    def test_short_nonempty_input_gets_neutral_prior(self):
        """Never reached in practice — is_votable_claim rejects under 24 chars."""
        assert 0.0 < contestation_score("x") < 0.5

    def test_score_stays_in_unit_interval(self):
        piled_on = ("Conscription should be mandatory and taxes raised rather than "
                    "subsidies cut, instead of tariffs banned at the expense of pensions.")
        assert 0.0 <= contestation_score(piled_on) <= 1.0
