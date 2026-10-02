"""The worked example on the product page.

One made-up consultation, used twice: visitors can answer it as a participant
would (``/consultations/demo``) and read the report it would produce
(``/consultations/example-report``). The votes are invented and labelled as
such wherever they appear, but every result is worked out by the same code as
a real report, so the example can never show a finding the product would not.
"""
from datetime import timedelta
from types import SimpleNamespace

from flask import current_app
from flask_babel import gettext as _

from app.lib.statement_results import VERDICT_ORDER, StatementTally, classify
from app.lib.time import utcnow_naive

NARRATIVE_EXAMPLE = 'example'

_PARTICIPANTS = 164
_INVITED = 420


def _statements() -> list:
    """``(id, wording, agree, disagree, unsure)``, in the order participants meet them."""
    return [
        (1, _('Members should vote on any spending above £10,000.'), 130, 14, 16),
        (2, _('The surplus should stay in reserves until the lease is renewed.'), 70, 65, 23),
        (3, _('Some of the surplus should go on lower fees for members.'), 112, 27, 19),
        (4, _('We should spend the surplus on a one-off event for members.'), 22, 118, 18),
        (5, _('We should hire a part-time coordinator with the surplus.'), 68, 72, 18),
        (6, _('We should publish a plain-English summary of the accounts every year.'), 139, 6, 11),
        (7, _('We should merge our reserves with the regional federation’s fund.'), 31, 36, 89),
        (8, _('A small grant fund for member projects would be money well spent.'), 98, 31, 27),
        (9, _('The committee should decide how to use the surplus without a member vote.'), 17, 131, 12),
        (10, _('We should refurbish the main hall before anything else.'), 96, 38, 22),
        (11, _('The surplus should be split equally between fees and the building.'), 74, 49, 33),
        (12, _('We should keep fees the same and improve what members get instead.'), 79, 52, 25),
    ]


def example_consultation() -> SimpleNamespace:
    """What the participant page needs to show the demonstration."""
    return SimpleNamespace(
        question=_('How should we use next year’s surplus?'),
        organisation_name=_('Riverside Members Club'),
        access_token='demo',
        show_results_to_participants=False,
        allow_audience_statements=False,
    )


def example_statements() -> list:
    return [{'id': statement_id, 'content': content} for statement_id, content, *_votes in _statements()]


def example_report_data() -> dict:
    """The example in the shape ``build_report_data`` produces."""
    results = []
    for statement_id, content, agree, disagree, unsure in _statements():
        result = classify(StatementTally(statement_id, agree=agree, disagree=disagree, unsure=unsure))
        results.append((result, content))
    results.sort(key=lambda pair: (VERDICT_ORDER.index(pair[0].verdict), -pair[0].strength))

    rows = []
    for result, content in results:
        row = result.to_dict()
        row['content'] = content
        row['source'] = 'host_written'
        rows.append(row)

    now = utcnow_naive()
    consultation = example_consultation()
    return {
        'version': 1,
        'question': consultation.question,
        'organisation_name': consultation.organisation_name,
        'audience_label': _('Members'),
        'audience_size': _INVITED,
        'opened_at': (now - timedelta(days=14)).replace(microsecond=0).isoformat(),
        'closed_at': (now - timedelta(days=7)).replace(microsecond=0).isoformat(),
        'generated_at': (now - timedelta(days=7)).replace(microsecond=0).isoformat(),
        'participant_count': _PARTICIPANTS,
        'vote_count': sum(row['total'] for row in rows),
        'statement_count': len(rows),
        'response_rate': round(_PARTICIPANTS / _INVITED, 4),
        'recommended_participants': current_app.config.get('CONSULTATION_RECOMMENDED_PARTICIPANTS', 30),
        'is_low_turnout': False,
        'counts': {
            verdict.value: sum(1 for row in rows if row['verdict'] == verdict.value) for verdict in VERDICT_ORDER
        },
        'statements': rows,
    }


def example_narrative() -> dict:
    """The kind of narrative a report carries. Held to ``validate_narrative``
    by the tests, like one the model wrote."""
    return {
        'language': 'en',
        'headline': _(
            'Participants want a say over large spending and clearer accounts, reject a one-off event, '
            'and are divided on whether to hold the surplus in reserve or hire a coordinator.'
        ),
        'themes': [
            {
                'title': _('Control and openness'),
                'summary': _(
                    'Participants agree that members should vote on large spending and that the accounts '
                    'should be published in plain English.'
                ),
                'verdict': 'agrees',
                'statement_ids': [1, 6],
            },
            {
                'title': _('Giving something back to members'),
                'summary': _('Participants agree with lower fees and with a grant fund for member projects.'),
                'verdict': 'agrees',
                'statement_ids': [3, 8],
            },
            {
                'title': _('What they do not want'),
                'summary': _(
                    'Participants disagree with a one-off event and with the committee deciding alone.'
                ),
                'verdict': 'disagrees',
                'statement_ids': [4, 9],
            },
            {
                'title': _('Reserves and staffing'),
                'summary': _(
                    'Participants are divided on keeping the surplus in reserve and on hiring a coordinator.'
                ),
                'verdict': 'split',
                'statement_ids': [2, 5],
            },
        ],
        'next_questions': [
            _('What would members need to know about the regional federation’s fund to take a view on merging reserves?'),
            _('What lies behind the division over holding the surplus until the lease is renewed?'),
            _('Which fees matter most to members?'),
        ],
    }
