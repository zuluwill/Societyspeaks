"""
Tests for app.trending.diversity_monitor module.
"""

import pytest
from app.trending.diversity_monitor import (
    get_political_leaning_label,
    assess_balance,
    _get_recommendation,
)
from app.trending.constants import (
    DIVERSITY_BALANCED_MIN,
    DIVERSITY_BALANCED_MAX,
    DIVERSITY_IMBALANCED_MIN,
    DIVERSITY_IMBALANCED_MAX,
)


class TestGetPoliticalLeaningLabel:
    """Tests for get_political_leaning_label function."""

    def test_none_returns_unknown(self):
        assert get_political_leaning_label(None) == 'unknown'

    def test_far_left(self):
        assert get_political_leaning_label(-2.0) == 'Left'
        assert get_political_leaning_label(-1.5) == 'Left'

    def test_centre_left(self):
        assert get_political_leaning_label(-1.0) == 'Centre-Left'
        assert get_political_leaning_label(-0.6) == 'Centre-Left'

    def test_centre(self):
        assert get_political_leaning_label(0.0) == 'Centre'
        assert get_political_leaning_label(-0.5) == 'Centre'
        assert get_political_leaning_label(0.5) == 'Centre'

    def test_centre_right(self):
        assert get_political_leaning_label(0.6) == 'Centre-Right'
        assert get_political_leaning_label(1.0) == 'Centre-Right'

    def test_right(self):
        assert get_political_leaning_label(1.5) == 'Right'
        assert get_political_leaning_label(2.0) == 'Right'


class TestAssessBalance:
    """Tests for assess_balance function."""

    def test_perfect_balance(self):
        result = assess_balance(1.0, 1.0)
        assert result['status'] == 'balanced'
        assert len(result['issues']) == 0

    def test_acceptable_left_lean(self):
        result = assess_balance(1.0, DIVERSITY_BALANCED_MAX - 0.1)
        assert result['status'] == 'balanced'

    def test_acceptable_right_lean(self):
        result = assess_balance(1.0, DIVERSITY_BALANCED_MIN + 0.1)
        assert result['status'] == 'balanced'

    def test_warning_left_lean(self):
        ratio = (DIVERSITY_BALANCED_MAX + DIVERSITY_IMBALANCED_MAX) / 2
        result = assess_balance(1.0, ratio)
        assert result['status'] == 'warning'
        assert any('left-leaning' in issue.lower() for issue in result['issues'])

    def test_warning_right_lean(self):
        ratio = (DIVERSITY_BALANCED_MIN + DIVERSITY_IMBALANCED_MIN) / 2
        result = assess_balance(1.0, ratio)
        assert result['status'] == 'warning'
        assert any('right-leaning' in issue.lower() for issue in result['issues'])

    def test_imbalanced_heavy_left(self):
        result = assess_balance(1.0, DIVERSITY_IMBALANCED_MAX + 0.5)
        assert result['status'] == 'imbalanced'
        assert any('heavily favors left' in issue.lower() for issue in result['issues'])

    def test_imbalanced_heavy_right(self):
        result = assess_balance(1.0, DIVERSITY_IMBALANCED_MIN - 0.1)
        assert result['status'] == 'imbalanced'
        assert any('heavily favors right' in issue.lower() for issue in result['issues'])

    def test_source_ratio_issues_reported(self):
        result = assess_balance(DIVERSITY_IMBALANCED_MAX + 1.0, 1.0)
        assert any('source ratio' in issue.lower() for issue in result['issues'])

    def test_recommendation_included(self):
        result = assess_balance(1.0, 1.0)
        assert 'recommendation' in result
        assert result['recommendation'] is not None


class TestGetRecommendation:
    """Tests for _get_recommendation function."""

    def test_balanced_no_action(self):
        rec = _get_recommendation('balanced', 1.0)
        assert 'no action' in rec.lower()

    def test_left_leaning_suggests_right_sources(self):
        rec = _get_recommendation('warning', DIVERSITY_BALANCED_MAX + 0.5)
        assert 'right-leaning' in rec.lower()

    def test_right_leaning_suggests_left_sources(self):
        rec = _get_recommendation('warning', DIVERSITY_BALANCED_MIN - 0.1)
        assert 'left-leaning' in rec.lower()

    def test_edge_case_monitor(self):
        rec = _get_recommendation('unknown', 1.0)
        assert 'monitor' in rec.lower()
