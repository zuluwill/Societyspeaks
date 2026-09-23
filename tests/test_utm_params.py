"""First-party email links must carry UTMs so PostHog does not call them Direct."""

from app.lib.utm import brief_email_utm_params, with_utm_filter, with_utm_params


def test_with_utm_params_preserves_fragment_and_existing_query():
    url = with_utm_params(
        'https://societyspeaks.io/brief/2026-09-23?src=brief_stance#stance',
        brief_email_utm_params(),
        content='stance',
    )
    assert 'src=brief_stance' in url
    assert 'utm_source=daily_brief' in url
    assert 'utm_medium=email' in url
    assert 'utm_campaign=brief' in url
    assert 'utm_content=stance' in url
    assert url.endswith('#stance')


def test_with_utm_params_does_not_clobber_existing_utms():
    url = with_utm_params(
        'https://societyspeaks.io/briefings/start?utm_source=landing&utm_campaign=hero',
        brief_email_utm_params(),
        content='cta',
    )
    assert 'utm_source=landing' in url
    assert 'utm_campaign=hero' in url
    assert 'utm_medium=email' in url
    assert 'utm_content=cta' in url


def test_with_utm_params_skips_mailto_and_empty():
    assert with_utm_params('mailto:hi@example.com', brief_email_utm_params()) == (
        'mailto:hi@example.com'
    )
    assert with_utm_params('', brief_email_utm_params()) == ''
    assert with_utm_params('#item-1', brief_email_utm_params()) == '#item-1'


def test_weekly_brief_source():
    params = brief_email_utm_params(source='weekly_brief')
    assert params['utm_source'] == 'weekly_brief'


def test_welcome_email_discussions_cta_is_tagged(app):
    from flask import render_template

    with app.app_context():
        html = render_template(
            'emails/welcome.html',
            username='Ada',
            verification_url='https://societyspeaks.io/auth/verify/x',
            base_url='https://societyspeaks.io',
        )
    assert 'utm_source=welcome' in html
    assert 'utm_content=discussions' in html
    assert 'utm_medium=email' in html


def test_jinja_filter_tags_methodology(app):
    with app.app_context():
        url = with_utm_filter(
            'https://societyspeaks.io/brief/methodology',
            'methodology',
            'daily_brief',
        )
        assert 'utm_content=methodology' in url
        assert 'utm_source=daily_brief' in url


def test_rendered_brief_email_tags_first_party_links(app, db):
    from datetime import date
    from unittest.mock import MagicMock, patch

    from app.brief.email_client import ResendClient
    from app.models import DailyBrief, DailyBriefSubscriber

    with app.app_context():
        brief = DailyBrief(
            date=date(2026, 9, 22),
            brief_type='daily',
            status='published',
            title='UTM edition',
        )
        sub = DailyBriefSubscriber(
            email='utm@example.com',
            status='active',
            magic_token='magic-utm',
            unsubscribe_token='unsub-utm',
        )
        db.session.add_all([brief, sub])
        db.session.commit()

        client = ResendClient.__new__(ResendClient)
        client._disabled = True
        client.api_key = 'test'
        client.rate_limiter = MagicMock()
        with patch('app.brief.email_client.get_base_url', return_value='https://societyspeaks.io'):
            html = client._render_email(sub, brief, sorted_items=[])

        assert 'utm_source=daily_brief' in html
        assert 'utm_medium=email' in html
        assert 'utm_content=web_brief' in html
        assert 'utm_content=methodology' in html
        assert 'utm_content=archive' in html
        # Account-management links stay token-only.
        assert '/brief/unsubscribe/unsub-utm?' not in html
        assert '/brief/preferences/magic-utm?' not in html


def test_weekly_digest_vote_urls_carry_utms_and_source(app, db):
    from datetime import date

    from app.daily.utils import build_question_email_data
    from app.models import DailyQuestion, DailyQuestionSubscriber

    with app.app_context():
        question = DailyQuestion(
            question_date=date(2026, 9, 22),
            question_number=9100,
            question_text='Should digest links keep a single query string?',
            status='published',
            source_type='discussion',
        )
        sub = DailyQuestionSubscriber(email='digest-utm@example.com', is_active=True)
        sub.generate_magic_token()
        db.session.add_all([question, sub])
        db.session.commit()

        data = build_question_email_data(
            question, sub, base_url='https://societyspeaks.io',
        )
        agree = data['vote_urls']['agree']
        assert 'source=weekly_digest' in agree
        assert 'utm_source=weekly_digest' in agree
        assert 'utm_content=stance_agree' in agree
        assert agree.count('?') == 1
        assert 'utm_source=weekly_digest' in data['question_url']


def test_digest_batch_and_cta_urls_are_tagged(app):
    from types import SimpleNamespace

    from app.resend_client import _digest_first_party_urls

    with app.app_context():
        subscriber = SimpleNamespace(magic_token='digest-token')
        questions = [SimpleNamespace(id=11), SimpleNamespace(id=12)]
        batch_url, cta_url = _digest_first_party_urls(
            'https://societyspeaks.io',
            subscriber,
            questions,
            source='weekly_digest',
        )

    assert 'token=digest-token' in batch_url
    assert 'questions=11,12' in batch_url
    assert 'utm_source=weekly_digest' in batch_url
    assert 'utm_content=batch' in batch_url
    assert batch_url.count('?') == 1
    assert 'utm_source=weekly_digest' in cta_url
    assert 'utm_campaign=personal_briefs_cta' in cta_url
