"""Notices to the host. One template, written in the host's language."""
import logging
from typing import List, Optional

from flask_babel import force_locale, format_date, gettext as _, ngettext

from app.lib.locale_utils import resolve_user_locale
from app.lib.url_utils import route_url
from app.storage_utils import get_base_url

logger = logging.getLogger(__name__)


def participant_url(consultation) -> str:
    return route_url(get_base_url(), 'consultations.participate', token=consultation.access_token)


def _host_url(endpoint: str, consultation) -> str:
    return route_url(get_base_url(), endpoint, consultation_id=consultation.id)


def invitation_text(consultation) -> str:
    """Ready-to-paste invitation for the host to send to their audience."""
    return _(
        '%(organisation)s wants to know what you think.\n\n'
        '“%(question)s”\n\n'
        'It takes about two minutes on your phone. There is no login and your answers are anonymous.\n\n'
        '%(link)s',
        organisation=consultation.organisation_name,
        question=consultation.question,
        link=participant_url(consultation),
    )


def reminder_text(consultation) -> str:
    """Ready-to-paste reminder for people who have not taken part yet."""
    return _(
        'A reminder: we would still like your view on “%(question)s”.\n\n'
        'It takes about two minutes, with no login, and your answers are anonymous. '
        'The more of us who take part, the clearer the picture.\n\n'
        '%(link)s',
        question=consultation.question,
        link=participant_url(consultation),
    )


def _send(
    consultation,
    *,
    subject: str,
    heading: str,
    paragraphs: List[str],
    cta_label: str,
    cta_url: str,
    quote: Optional[str] = None,
) -> bool:
    from app.resend_client import _send_user_transactional_email

    owner = consultation.owner
    if owner is None:
        return False
    return _send_user_transactional_email(
        owner,
        'emails/consultation_notice.html',
        subject,
        {
            'heading': heading,
            'question': consultation.question,
            'paragraphs': paragraphs,
            'quote': quote,
            'cta_label': cta_label,
            'cta_url': cta_url,
        },
    )


def _in_host_language(consultation):
    return force_locale(resolve_user_locale(consultation.owner))


def notify_live(consultation) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('Your consultation is live'),
            heading=_('Your consultation is live'),
            paragraphs=[
                _('People can now take part. Share the link or the QR code with your audience.'),
                _('We will email you when the first responses arrive and when your report is ready.'),
            ],
            quote=participant_url(consultation),
            cta_label=_('Get the link and QR code'),
            cta_url=_host_url('consultations.share', consultation),
        )


def notify_first_responses(consultation, participants: int) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('The first responses are in'),
            heading=_('The first responses are in'),
            paragraphs=[
                ngettext(
                    '%(num)d person has taken part so far.',
                    '%(num)d people have taken part so far.',
                    participants,
                ),
                _('You can watch results come in on your dashboard. The report is built when voting closes.'),
            ],
            cta_label=_('Open the dashboard'),
            cta_url=_host_url('consultations.dashboard', consultation),
        )


def notify_access_ending(user, ends_at, *, question: str) -> bool:
    """Tell the host that open consultations close when access ends."""
    from app.resend_client import _send_user_transactional_email

    if user is None:
        return False
    with force_locale(resolve_user_locale(user)):
        when = format_date(ends_at, 'd MMMM y')
        return _send_user_transactional_email(
            user,
            'emails/consultation_notice.html',
            _('Your consultation access ends on %(date)s', date=when),
            {
                'heading': _('Your access ends on %(date)s', date=when),
                'question': question,
                'paragraphs': [
                    _('Any consultation still open will close then, and the report will be built.'),
                    _('You can keep it open by paying for 30 days or for the year. People can keep taking part until you do, and afterwards.'),
                    _('A report that has already been built stays readable and downloadable.'),
                ],
                'quote': None,
                'cta_label': _('Continue for 30 days or a year'),
                'cta_url': route_url(get_base_url(), 'consultations.account'),
            },
        )


def notify_closing_soon(consultation, participants: int, recommended: int) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('Your consultation closes tomorrow'),
            heading=_('Closing tomorrow, and turnout is low'),
            paragraphs=[
                ngettext(
                    '%(num)d person has taken part so far.',
                    '%(num)d people have taken part so far.',
                    participants,
                ) + ' ' + _(
                    'Clear results usually need %(recommended)d or more.', recommended=recommended,
                ),
                _('A reminder often doubles turnout. Here is one you can paste and send:'),
                _('You can also keep the consultation open for longer from your dashboard.'),
            ],
            quote=reminder_text(consultation),
            cta_label=_('Extend or send a reminder'),
            cta_url=_host_url('consultations.dashboard', consultation),
        )


def notify_report_ready(consultation) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('Your consultation report is ready'),
            heading=_('Your report is ready'),
            paragraphs=[
                _('Voting has closed and your report has been built from the results.'),
                _('Only you can see it. Read it first, then choose whether to share it.'),
            ],
            cta_label=_('Read your report'),
            cta_url=_host_url('consultations.report', consultation),
        )


def notify_statements_waiting(consultation, waiting: int) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('Suggested statements are waiting for you'),
            heading=_('Your audience has suggested statements'),
            paragraphs=[
                ngettext(
                    '%(num)d suggestion is waiting for your approval.',
                    '%(num)d suggestions are waiting for your approval.',
                    waiting,
                ),
                _('Nothing a participant suggests is shown to anyone until you approve it.'),
            ],
            cta_label=_('Review suggestions'),
            cta_url=_host_url('consultations.moderation', consultation),
        )


def notify_drafting_failed(consultation) -> bool:
    with _in_host_language(consultation):
        return _send(
            consultation,
            subject=_('We could not draft your statements'),
            heading=_('We could not draft your statements'),
            paragraphs=[
                _('The drafting service did not respond after several tries. Nothing you entered has been lost.'),
                _('You can try again, or write the statements yourself. The page shows what makes a good one.'),
            ],
            cta_label=_('Continue your consultation'),
            cta_url=_host_url('consultations.statements', consultation),
        )
