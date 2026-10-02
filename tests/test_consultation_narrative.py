"""The report narrative may describe findings and must never quantify them."""
import pytest

from app.consultations.narrative import ai_narrative, template_narrative, validate_narrative


def _row(statement_id, verdict, content='A statement about the question.', lean=None):
    return {
        'statement_id': statement_id, 'verdict': verdict, 'lean': lean, 'content': content,
        'agree': 20, 'disagree': 5, 'unsure': 5, 'total': 30,
        'agree_share': 0.6667, 'disagree_share': 0.1667, 'unsure_share': 0.1667,
    }


@pytest.fixture
def data():
    rows = [
        _row(1, 'agrees', 'We should lower fees.'),
        _row(2, 'agrees', 'We should publish the accounts.'),
        _row(3, 'disagrees', 'We should close the cafe.'),
        _row(4, 'split', 'We should move premises.'),
        _row(5, 'unsure', 'We should merge with the other club.'),
        _row(6, 'no_clear_result', 'We should hire a manager.', lean='agree'),
    ]
    counts = {'agrees': 2, 'disagrees': 1, 'unsure': 1, 'split': 1, 'no_clear_result': 1, 'too_few_votes': 0}
    return {
        'question': 'What should we do next?', 'organisation_name': 'Club', 'audience_label': None,
        'statement_count': 6, 'counts': counts, 'statements': rows,
    }


def _narrative(**overrides):
    narrative = {
        'language': 'en',
        'headline': 'Participants back lower fees and open accounts, and are divided on moving premises.',
        'themes': [
            {'title': 'Money and openness', 'summary': 'Participants agree on lower fees and on publishing the accounts.',
             'verdict': 'agrees', 'statement_ids': [1, 2]},
            {'title': 'Premises', 'summary': 'Participants are divided on whether to move.',
             'verdict': 'split', 'statement_ids': [4]},
        ],
        'next_questions': ['What would make a move worthwhile for those who oppose it?'],
    }
    narrative.update(overrides)
    return narrative


def test_a_faithful_narrative_passes(data):
    assert validate_narrative(_narrative(), data) is None


@pytest.mark.parametrize('headline', [
    '67% of participants want lower fees.',
    'Two thirds of participants want lower fees.',
    'Half of participants want lower fees.',
    'Participants were unanimous on lower fees.',
    'Everyone wants lower fees.',
    'Support was overwhelming for lower fees.',
    '20 people backed lower fees.',
])
def test_a_narrative_that_quantifies_is_rejected(data, headline):
    assert validate_narrative(_narrative(headline=headline), data) is not None


def test_a_theme_must_cite_statements_that_have_its_result(data):
    wrong_result = _narrative(themes=[{
        'title': 'Cafe', 'summary': 'Participants agree the cafe should close.',
        'verdict': 'agrees', 'statement_ids': [3],
    }])
    unknown_statement = _narrative(themes=[{
        'title': 'Other', 'summary': 'Participants agree.', 'verdict': 'agrees', 'statement_ids': [99],
    }])
    uncited = _narrative(themes=[{
        'title': 'Other', 'summary': 'Participants agree.', 'verdict': 'agrees', 'statement_ids': [],
    }])
    from_a_lean = _narrative(themes=[{
        'title': 'Manager', 'summary': 'Participants agree on hiring a manager.',
        'verdict': 'agrees', 'statement_ids': [6],
    }])

    for narrative in (wrong_result, unknown_statement, uncited, from_a_lean):
        assert validate_narrative(narrative, data) is not None


def test_an_overlong_or_empty_narrative_is_rejected(data):
    assert validate_narrative(_narrative(headline=''), data) is not None
    assert validate_narrative(_narrative(headline='x' * 400), data) is not None
    assert validate_narrative(_narrative(next_questions=['q?'] * 9), data) is not None


def test_the_template_narrative_counts_from_the_data(app, data):
    with app.test_request_context():
        narrative = template_narrative(data)

    assert narrative['headline'] == (
        'Of 6 statements, participants clearly agreed with 2, clearly disagreed with 1, '
        'were unsure about 1, and were split on 1.'
    )
    assert narrative['themes'] == []
    assert any('We should move premises.' in question for question in narrative['next_questions'])


def test_no_findings_means_no_model_call_and_an_honest_headline(app, data, monkeypatch):
    monkeypatch.setattr(
        'app.consultations.narrative.complete_json',
        lambda **kwargs: pytest.fail('the model must not be asked to describe nothing'),
    )
    data['counts'] = {key: 0 for key in data['counts']}
    data['counts']['too_few_votes'] = 6

    assert ai_narrative(data) is None
    with app.test_request_context():
        assert 'Too few people have taken part' in template_narrative(data)['headline']


def test_the_model_is_given_results_as_labels_never_as_numbers(app, data, monkeypatch):
    prompts = []

    def _complete(**kwargs):
        prompts.append(kwargs['prompt'])
        return _narrative()

    monkeypatch.setattr('app.consultations.narrative.complete_json', _complete)

    narrative = ai_narrative(data)

    assert narrative['headline'].startswith('Participants back lower fees')
    assert '[agrees]' in prompts[0] and '[no_clear_result (leans agree)]' in prompts[0]
    assert '0.6667' not in prompts[0] and '20' not in prompts[0] and '30' not in prompts[0]


def test_a_rejected_narrative_is_retried_once_then_dropped(app, data, monkeypatch):
    calls = []

    def _complete(**kwargs):
        calls.append(1)
        return _narrative(headline='67% of participants want lower fees.')

    monkeypatch.setattr('app.consultations.narrative.complete_json', _complete)

    assert ai_narrative(data) is None
    assert len(calls) == 2


@pytest.mark.parametrize('headline', [
    'Nine in ten participants backed lower fees.',
    'Participants backed lower fees by a margin of three to one.',
    'Twice as many participants agreed as disagreed about fees.',
    'Nearly all participants backed lower fees.',
    'A vast majority of participants backed lower fees.',
    'Dozens of participants backed lower fees.',
])
def test_numbers_and_proportions_written_as_words_are_rejected(data, headline):
    assert 'quantifies' in validate_narrative(_narrative(headline=headline), data)


def test_a_figure_from_the_hosts_own_wording_may_be_repeated(data):
    data['question'] = 'Should we move to a 4-day week?'
    data['statements'][0]['content'] = 'A 4-day week would help me.'

    assert validate_narrative(_narrative(headline='Participants back the 4-day week.'), data) is None
    assert 'quantifies' in validate_narrative(_narrative(headline='Participants back the 5-day week.'), data)


def test_a_narrative_in_another_checked_language_is_held_to_the_same_rule(data):
    french = _narrative(
        language='fr',
        headline='Les participants soutiennent la baisse des cotisations.',
        themes=[], next_questions=[],
    )
    assert validate_narrative(french, data) is None

    french['headline'] = 'La moitié des participants soutient la baisse des cotisations.'
    assert 'quantifies' in validate_narrative(french, data)


def test_a_narrative_whose_wording_cannot_be_checked_is_not_published(data):
    assert 'cannot be checked' in validate_narrative(_narrative(language='other'), data)
    assert 'cannot be checked' in validate_narrative(_narrative(headline='参与者支持降低会费。'), data)


def test_the_model_is_not_asked_for_a_narrative_it_could_not_publish(data, monkeypatch):
    monkeypatch.setattr(
        'app.consultations.narrative.complete_json',
        lambda **kwargs: pytest.fail('a narrative in this script could never pass validation'),
    )
    data['question'] = '我们明年应该怎样使用盈余？'

    assert ai_narrative(data) is None


def test_a_rejected_draft_is_sent_back_with_the_reason(data, monkeypatch):
    prompts = []

    def _complete(**kwargs):
        prompts.append(kwargs['prompt'])
        if len(prompts) == 1:
            return _narrative(headline='Nine in ten participants backed lower fees.')
        return _narrative()

    monkeypatch.setattr('app.consultations.narrative.complete_json', _complete)

    assert ai_narrative(data)['headline'].startswith('Participants back lower fees')
    assert 'previous draft could not be used' in prompts[1] and 'Nine' in prompts[1]
