# app/help/routes.py
from flask import render_template, url_for, current_app
from flask_babel import gettext as _

from app.help import help_bp


def _help_categories():
    """Help hub cards — titles/descriptions are translated at render time."""
    cats = [
        {
            'key': 'getting-started',
            'title': _('Getting Started'),
            'description': _('How to participate, save progress, and explore the platform'),
            'icon': 'book-open',
            'url': url_for('help.getting_started'),
            'section': 'participate',
        },
        {
            'key': 'big-questions',
            'title': _('Big Questions Journey'),
            'description': _('Guided civic experience across 8 themes and country editions'),
            'icon': 'lightning',
            'url': url_for('help.big_questions_journey'),
            'section': 'participate',
        },
        {
            'key': 'daily-question',
            'title': _('Daily Question'),
            'description': _('One civic question a day — vote, reflect, then see how others responded'),
            'icon': 'clock',
            'url': url_for('help.daily_question'),
            'section': 'daily',
        },
        {
            'key': 'daily-brief',
            'title': _('Daily Brief'),
            'description': _('Free editorial digest from 140+ sources across the spectrum'),
            'icon': 'newspaper',
            'url': url_for('help.daily_brief'),
            'section': 'daily',
        },
        {
            'key': 'news-dashboard',
            'title': _('News Transparency Dashboard'),
            'description': _('Explore how today\'s stories are covered left, centre, and right'),
            'icon': 'globe',
            'url': url_for('help.news_dashboard'),
            'section': 'daily',
        },
        {
            'key': 'civic-infrastructure',
            'title': _('Civic infrastructure'),
            'description': _('Run programmes, ship your own questions, polls, and consultations'),
            'icon': 'building',
            'url': url_for('help.civic_infrastructure'),
            'section': 'build',
        },
        {
            'key': 'programmes',
            'title': _('Programmes'),
            'description': _('Multi-discussion campaigns with themes, phases, and exports'),
            'icon': 'layers',
            'url': url_for('help.programmes'),
            'section': 'build',
        },
        {
            'key': 'creating-discussions',
            'title': _('Creating Discussions'),
            'description': _('Launch structured polls and deliberation spaces in minutes'),
            'icon': 'message-circle',
            'url': url_for('help.creating_discussions'),
            'section': 'build',
        },
        {
            'key': 'managing-discussions',
            'title': _('Managing Discussions'),
            'description': _('Moderation, stewards, exports, and reading results'),
            'icon': 'settings',
            'url': url_for('help.managing_discussions'),
            'section': 'build',
        },
        {
            'key': 'personal-briefs',
            'title': _('Personal Briefs'),
            'description': _('Custom AI digests from your sources — funds the free civic platform'),
            'icon': 'brief',
            'url': url_for('help.personal_briefs'),
            'section': 'build',
        },
        {
            'key': 'native-system',
            'title': _('Native deliberation system'),
            'description': _('Statements, voting, clustering, consensus, and bridge ideas'),
            'icon': 'chart',
            'url': url_for('help.native_system'),
            'section': 'technical',
        },
        {
            'key': 'news-feed',
            'title': _('News sourcing for discussions'),
            'description': _('How trending topics become balanced deliberation prompts'),
            'icon': 'rss',
            'url': url_for('help.news_feed'),
            'section': 'technical',
        },
    ]
    if current_app.config.get('GAME_ENABLED', True):
        cats.insert(
            4,
            {
                'key': 'tradeoffs',
                'title': _('Tradeoffs'),
                'description': _('Daily scenarios — govern under pressure, see who you become'),
                'icon': 'scale',
                'url': url_for('help.tradeoffs'),
                'section': 'daily',
            },
        )
    return cats


@help_bp.route('/')
def help():
    categories = _help_categories()
    sections = [
        ('participate', _('Participate')),
        ('daily', _('Daily civic habit')),
        ('build', _('Build & run consultations')),
        ('technical', _('Technical depth')),
    ]
    return render_template(
        'help/help.html',
        categories=categories,
        sections=sections,
        game_enabled=current_app.config.get('GAME_ENABLED', True),
    )


@help_bp.route('/getting-started')
def getting_started():
    return render_template('help/getting_started.html')


@help_bp.route('/big-questions-journey')
def big_questions_journey():
    return render_template('help/big_questions_journey.html')


@help_bp.route('/daily-question')
def daily_question():
    return render_template('help/daily_question.html')


@help_bp.route('/daily-brief')
def daily_brief():
    return render_template('help/daily_brief.html')


@help_bp.route('/tradeoffs')
def tradeoffs():
    if not current_app.config.get('GAME_ENABLED', True):
        from flask import abort
        abort(404)
    return render_template('help/tradeoffs.html')


@help_bp.route('/personal-briefs')
def personal_briefs():
    return render_template('help/personal_briefs.html')


@help_bp.route('/news-dashboard')
def news_dashboard():
    return render_template('help/news_dashboard.html')


@help_bp.route('/civic-infrastructure')
def civic_infrastructure():
    return render_template('help/civic_infrastructure.html')


@help_bp.route('/creating-discussions')
def creating_discussions():
    return render_template('help/creating_discussions.html')


@help_bp.route('/managing-discussions')
def managing_discussions():
    return render_template('help/managing_discussions.html')


@help_bp.route('/seed-comments')
def seed_comments():
    return render_template('help/seed_comments.html')


@help_bp.route('/polis-algorithms')
def polis_algorithms():
    return render_template('help/polis_algorithms.html')


@help_bp.route('/native-system')
def native_system():
    return render_template('help/native_system.html')


@help_bp.route('/news-feed')
def news_feed():
    return render_template('help/news_feed.html')


@help_bp.route('/programmes')
def programmes():
    return render_template('help/programmes.html')
