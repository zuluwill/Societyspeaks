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


# ── The product page ────────────────────────────────────────────────────────

# One statement for each kind of finding, in the order the product page lets a
# visitor answer them.
_HIGHLIGHT_IDS = (1, 4, 7, 2)


def example_highlights() -> list:
    """Four rows of the worked example, one per kind of finding."""
    rows = {row['statement_id']: row for row in example_report_data()['statements']}
    return [rows[statement_id] for statement_id in _HIGHLIGHT_IDS]


def _use_cases() -> list:
    """``(key, sector, question, how it was shared, took part, findings)``.

    Each finding is ``(wording, agree, disagree, unsure, what it lets you do)``.
    """
    return [
        (
            'members', _('Membership bodies'),
            _('Should we raise membership fees next year?'),
            _('Link in the members’ newsletter, open for a week'), 212,
            [
                (_('A rise of up to £10 a year is acceptable if services are protected.'), 156, 30, 26,
                 _('Take a rise of up to £10 to the AGM, tied to protecting services.')),
                (_('Fees should be frozen, even if it means cutting the events programme.'), 40, 150, 22,
                 _('Take the freeze off the table.')),
                (_('Paying monthly would make membership easier to afford.'), 52, 38, 122,
                 _('Explain how monthly payments would work, then ask again.')),
                (_('Members under 30 should pay a lower fee.'), 96, 88, 28,
                 _('Do not force a vote yet. Find out what each side is worried about.')),
            ],
        ),
        (
            'charities', _('Charities and trustees'),
            _('Where should we focus over the next three years?'),
            _('Emailed to staff and volunteers before the board away-day'), 86,
            [
                (_('We should do fewer things and do them better.'), 64, 10, 12,
                 _('Give the board a mandate to shorten the programme list.')),
                (_('We should open a second site.'), 14, 58, 14,
                 _('Drop the second site from the draft strategy.')),
                (_('Our reserves are large enough for us to take more risk.'), 15, 17, 54,
                 _('Share the reserves position in plain figures before asking again.')),
                (_('We should take on more government contracts.'), 36, 38, 12,
                 _('Put contracts on the away-day agenda as an open question.')),
            ],
        ),
        (
            'teams', _('Teams and staff'),
            _('How should we work together from January?'),
            _('Link in the all-staff message, open for three days'), 58,
            [
                (_('Two fixed office days a week would work for me.'), 41, 9, 8,
                 _('Set two fixed days, knowing most of the team is behind it.')),
                (_('Everyone should be in the office five days a week.'), 5, 48, 5,
                 _('Stop spending meetings on a full return.')),
                (_('It is clear what is expected of me on the days I work from home.'), 12, 14, 32,
                 _('Write down what a home-working day should look like.')),
                (_('Each team should choose its own office days.'), 25, 24, 9,
                 _('Try both ways in two teams before choosing.')),
            ],
        ),
        (
            'events', _('Events and conferences'),
            _('What should our sector do about AI this year?'),
            _('QR code on the opening slide of the closing panel'), 118,
            [
                (_('Every organisation here needs a written AI policy this year.'), 92, 12, 14,
                 _('Open the panel with it: the room has already decided.')),
                (_('We should stop using AI tools until regulation catches up.'), 13, 90, 15,
                 _('Skip the debate about a ban.')),
                (_('I understand how AI tools use my organisation’s data.'), 20, 24, 74,
                 _('Plan a follow-up session on data.')),
                (_('AI will cut the number of jobs in our sector within five years.'), 50, 47, 21,
                 _('Hand the split to the panel as its first question.')),
            ],
        ),
        (
            'research', _('Think tanks and researchers'),
            _('How should the city pay for better buses?'),
            _('Sent to newsletter readers alongside the draft paper'), 326,
            [
                (_('Bus fares should be capped at £2.'), 251, 40, 35,
                 _('Lead the paper with the proposal readers back.')),
                (_('Cutting quiet routes to pay for busier ones is acceptable.'), 46, 232, 48,
                 _('Record it as a red line.')),
                (_('Franchising would give the city better buses than it has now.'), 62, 49, 215,
                 _('Explain franchising before asking for a view on it.')),
                (_('A workplace parking levy is a fair way to pay for buses.'), 137, 142, 47,
                 _('Run a second, narrower consultation on the levy.')),
            ],
        ),
        (
            'publishers', _('Publishers and podcasts'),
            _('Should the voting age be lowered to 16?'),
            _('Link in the show notes after the episode'), 540,
            [
                (_('Schools should teach pupils how to register and vote.'), 464, 38, 38,
                 _('Report back what your audience agrees on in the next episode.')),
                (_('Sixteen-year-olds are too easily influenced to vote.'), 152, 313, 75,
                 _('Say plainly that your audience rejects the argument.')),
                (_('Lowering the voting age would change who wins elections.'), 108, 97, 335,
                 _('Make the evidence the subject of an episode.')),
                (_('The voting age should be 16 for every UK election.'), 232, 227, 81,
                 _('Invite a guest from each side of the split.')),
            ],
        ),
    ]


def _use_case_stories() -> dict:
    """``key -> (the situation the question comes out of, what the findings add up to)``."""
    return {
        'members': (
            _('The AGM is three weeks away, costs are up, and the loudest members want a freeze.'),
            _('A modest rise has a mandate. The freeze the loudest members wanted does not.'),
        ),
        'charities': (
            _('The board sets the strategy next month. Staff and volunteers have views nobody has asked for.'),
            _('People want focus, not growth. On reserves they need figures, not persuasion.'),
        ),
        'teams': (
            _('The lease is up for renewal. Everyone has a view on office days and nobody says it in the all-hands.'),
            _('Two fixed days is settled. The real argument is over who chooses them.'),
        ),
        'events': (
            _('Three hundred people, one panel, forty minutes. The same five would ask all the questions.'),
            _('The room wants a policy, not a ban, and is unsure how AI tools use its data.'),
        ),
        'research': (
            _('The draft paper makes four proposals. You want to know which will land before you publish.'),
            _('The fare cap is the headline. The parking levy needs more work before it goes in the paper.'),
        ),
        'publishers': (
            _('The episode drew more replies than any other. Replies only tell you what the keenest listeners think.'),
            _('Your audience agrees on teaching it in schools and is evenly divided on the vote itself.'),
        ),
    }


def use_case_examples() -> list:
    """Made-up consultations for the product page, one per kind of organisation.

    Each shows one finding of each kind, worked out by ``classify`` like the
    worked example above.
    """
    examples = []
    stories = _use_case_stories()
    for key, sector, question, how, participants, findings in _use_cases():
        rows = []
        for index, (content, agree, disagree, unsure, action) in enumerate(findings, start=1):
            row = classify(StatementTally(index, agree=agree, disagree=disagree, unsure=unsure)).to_dict()
            row['content'] = content
            row['action'] = action
            rows.append(row)
        examples.append({
            'key': key,
            'sector': sector,
            'question': question,
            'situation': stories[key][0],
            'takeaway': stories[key][1],
            'how': how,
            'participant_count': participants,
            'findings': rows,
        })
    return examples
