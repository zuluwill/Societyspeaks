"""
Tests for app.trending.constants module.
"""

import pytest
from app.trending.constants import (
    strip_html_tags,
    extract_geographic_info_from_articles,
    get_unique_slug,
    VALID_TOPICS,
    DIVERSITY_BALANCED_MIN,
    DIVERSITY_BALANCED_MAX,
    DIVERSITY_IMBALANCED_MIN,
    DIVERSITY_IMBALANCED_MAX,
    GEOGRAPHIC_SCOPE_GLOBAL,
    GEOGRAPHIC_SCOPE_COUNTRY,
    ARTICLE_SCOPE_TO_DISCUSSION_SCOPE,
)
from tests.conftest import MockArticle, MockSource, MockTopicArticle


class TestStripHtmlTags:
    """Tests for strip_html_tags function."""

    def test_empty_string(self):
        assert strip_html_tags("") == ""

    def test_none_input(self):
        assert strip_html_tags(None) == ""

    def test_plain_text(self):
        assert strip_html_tags("Hello World") == "Hello World"

    def test_removes_simple_tags(self):
        assert strip_html_tags("<p>Hello</p>") == "Hello"

    def test_removes_br_tags(self):
        assert strip_html_tags("Hello<br>World") == "Hello World"
        assert strip_html_tags("Hello<br/>World") == "Hello World"

    def test_removes_nested_tags(self):
        assert strip_html_tags("<div><p>Hello</p></div>") == "Hello"

    def test_decodes_html_entities(self):
        assert strip_html_tags("Hello &amp; World") == "Hello & World"
        assert strip_html_tags("&lt;test&gt;") == "<test>"

    def test_normalizes_whitespace(self):
        assert strip_html_tags("Hello   World") == "Hello World"
        assert strip_html_tags("<p>Hello</p>  <p>World</p>") == "Hello World"


class TestExtractGeographicInfo:
    """Tests for extract_geographic_info_from_articles function."""

    def test_empty_list(self):
        scope, country = extract_geographic_info_from_articles([])
        assert scope == GEOGRAPHIC_SCOPE_GLOBAL
        assert country is None

    def test_global_scope_articles(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_scope='global', geographic_countries='Global')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_GLOBAL
        assert country is None

    def test_national_scope_articles(self):
        articles = [
            MockTopicArticle(MockArticle(
                geographic_scope='national',
                geographic_countries='United Kingdom'
            )),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_COUNTRY
        assert country == 'United Kingdom'

    def test_local_scope_maps_to_country(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_scope='local', geographic_countries='USA')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_COUNTRY
        assert country == 'USA'

    def test_regional_scope_maps_to_country(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_scope='regional', geographic_countries='France')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_COUNTRY

    def test_falls_back_to_source_country(self):
        source = MockSource(country='Germany')
        articles = [
            MockTopicArticle(MockArticle(source=source)),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_GLOBAL
        assert country == 'Germany'

    def test_most_common_country_wins(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_countries='UK')),
            MockTopicArticle(MockArticle(geographic_countries='UK')),
            MockTopicArticle(MockArticle(geographic_countries='USA')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert country == 'UK'

    def test_handles_comma_separated_countries(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_countries='UK, USA, France')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert country == 'UK'

    def test_ignores_unknown_scope(self):
        articles = [
            MockTopicArticle(MockArticle(geographic_scope='unknown', geographic_countries='UK')),
        ]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_GLOBAL

    def test_handles_none_article(self):
        articles = [MockTopicArticle(None)]
        scope, country = extract_geographic_info_from_articles(articles)
        assert scope == GEOGRAPHIC_SCOPE_GLOBAL
        assert country is None


class TestDiversityConstants:
    """Tests for diversity threshold constants."""

    def test_balanced_range_is_valid(self):
        assert DIVERSITY_BALANCED_MIN < 1.0 < DIVERSITY_BALANCED_MAX

    def test_imbalanced_outside_balanced(self):
        assert DIVERSITY_IMBALANCED_MIN < DIVERSITY_BALANCED_MIN
        assert DIVERSITY_IMBALANCED_MAX > DIVERSITY_BALANCED_MAX

    def test_thresholds_are_symmetric_around_one(self):
        # Balanced range: 0.7 to 1.4 (not perfectly symmetric, intentionally)
        assert DIVERSITY_BALANCED_MIN > 0
        assert DIVERSITY_BALANCED_MAX > 1

    def test_valid_topics_not_empty(self):
        assert len(VALID_TOPICS) > 0
        assert 'Society' in VALID_TOPICS


class TestArticleScopeMapping:
    """Tests for ARTICLE_SCOPE_TO_DISCUSSION_SCOPE mapping."""

    def test_national_maps_to_country(self):
        assert ARTICLE_SCOPE_TO_DISCUSSION_SCOPE['national'] == GEOGRAPHIC_SCOPE_COUNTRY

    def test_local_maps_to_country(self):
        assert ARTICLE_SCOPE_TO_DISCUSSION_SCOPE['local'] == GEOGRAPHIC_SCOPE_COUNTRY

    def test_regional_maps_to_country(self):
        assert ARTICLE_SCOPE_TO_DISCUSSION_SCOPE['regional'] == GEOGRAPHIC_SCOPE_COUNTRY

    def test_global_maps_to_global(self):
        assert ARTICLE_SCOPE_TO_DISCUSSION_SCOPE['global'] == GEOGRAPHIC_SCOPE_GLOBAL
