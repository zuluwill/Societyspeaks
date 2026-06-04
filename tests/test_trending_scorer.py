"""Unit tests for trending article scorer helpers (JSON parse, truncation handling)."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.trending.scorer import (
    _apply_openai_scores,
    _score_batch_with_openai,
    _sanitize_for_json,
    extract_json,
)
from tests.conftest import MockArticle


class TestExtractJson:
    def test_parses_markdown_fenced_object(self):
        raw = 'Here you go:\n```json\n{"scores": [{"s": 0.1}]}\n```\nThanks'
        assert extract_json(raw) == {'scores': [{'s': 0.1}]}

    def test_parses_bare_array(self):
        assert extract_json('[{"s": 0.5, "r": 0.8}]') == [{'s': 0.5, 'r': 0.8}]

    def test_raises_on_empty(self):
        with pytest.raises(ValueError, match='Empty'):
            extract_json('')

    def test_raises_on_invalid_json(self):
        with pytest.raises(ValueError, match='Invalid JSON'):
            extract_json('not json at all')


class TestSanitizeForJson:
    def test_strips_control_chars_keeps_newline_tab(self):
        dirty = 'Line\x00one\tTab\x1f'
        assert _sanitize_for_json(dirty) == 'Lineone\tTab'


class TestOpenAIBatchBisection:
    @staticmethod
    def _openai_response(finish_reason, content):
        choice = MagicMock()
        choice.finish_reason = finish_reason
        choice.message.content = content
        response = MagicMock()
        response.choices = [choice]
        return response

    def test_bisects_on_truncated_response(self):
        articles = [_make_scorer_article(f'Title {i}') for i in range(4)]

        full_payload = json.dumps({
            'scores': [
                {'s': 0.1, 'r': 0.2, 'p': 0.3, 'geo': 'national', 'countries': 'United Kingdom'}
                for _ in range(2)
            ]
        })
        truncated = self._openai_response('length', None)
        ok = self._openai_response('stop', full_payload)

        client = MagicMock()
        client.chat.completions.create.side_effect = [truncated, ok, ok]

        _score_batch_with_openai(articles, client, max_tokens=100, _depth=0)

        assert client.chat.completions.create.call_count == 3
        assert articles[0].sensationalism_score == 0.1
        assert articles[3].sensationalism_score == 0.1

    def test_heuristic_fallback_when_single_article_still_truncated(self):
        articles = [_make_scorer_article('BREAKING: You Won\'t Believe This!!!')]

        truncated = self._openai_response('length', None)
        client = MagicMock()
        client.chat.completions.create.return_value = truncated

        _score_batch_with_openai(articles, client, max_tokens=50, _depth=3)

        assert articles[0].sensationalism_score is not None
        assert articles[0].sensationalism_score > 0


def _make_scorer_article(title='Headline'):
    article = MockArticle()
    article.title = title
    article.summary = ''
    article.relevance_score = 0.5
    article.source = None
    article.sensationalism_score = None
    article.personal_relevance_score = None
    article.geographic_scope = None
    article.geographic_countries = None
    return article


class TestApplyOpenaiScores:
    def test_partial_scores_use_heuristic_for_missing_tail(self):
        article = _make_scorer_article('Shocking policy debate')
        _apply_openai_scores([article], [{'s': 0.2, 'r': 0.9, 'p': 0.8, 'geo': 'national', 'countries': 'Global'}])
        assert article.sensationalism_score == 0.2
        assert article.personal_relevance_score == 0.8

    def test_missing_score_row_gets_heuristic(self):
        articles = [_make_scorer_article('A'), _make_scorer_article('B')]
        _apply_openai_scores(articles, [{'s': 0.1, 'r': 0.2, 'p': 0.3, 'geo': 'local', 'countries': 'United Kingdom'}])
        assert articles[1].sensationalism_score is not None
