"""
Partner Hub Routes

Routes for the partner-facing pages:
- /for-publishers - Partner hub landing page
- /for-publishers/embed - Embed code generator
- /for-publishers/api - API documentation
- /for-publishers/rules - Rules of the Record
"""
from flask import render_template, request, current_app
from app.partner import partner_bp
from app.partner.constants import EMBED_THEMES, EMBED_ALLOWED_FONTS


@partner_bp.route('/')
def hub():
    """
    Partner hub landing page.

    Explains Society Speaks as the public reasoning layer, the three primitives
    (Judgment Prompt, Audience Snapshot, Understanding Link), and provides
    links to the embed generator and API documentation.
    """
    return render_template('partner/hub.html')


@partner_bp.route('/embed')
def embed_generator():
    """
    Embed code generator.

    Partners can enter an article URL or discussion ID, pick a theme,
    and get a ready-to-paste iframe snippet.
    """
    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
    return render_template(
        'partner/embed_generator.html',
        themes=EMBED_THEMES,
        fonts=EMBED_ALLOWED_FONTS,
        base_url=base_url
    )


@partner_bp.route('/api')
def api_docs():
    """
    API documentation page.

    Documents the lookup API, snapshot API, and embed URL parameters.
    """
    base_url = current_app.config.get('BASE_URL', 'https://societyspeaks.io')
    return render_template('partner/api_docs.html', base_url=base_url)


@partner_bp.route('/rules')
def rules_of_record():
    """
    Rules of the Record page.

    Plain English explanation of what partners may and may not do.
    """
    return render_template('partner/rules.html')
