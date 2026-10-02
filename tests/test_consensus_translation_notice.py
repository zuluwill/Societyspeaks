"""
"Translation in progress" must track the content actually on the page.

Both the results page and the report summed their per-section statement
counts and compared that with ``translation_map|length``, which is keyed by
unique statement id. Anything every group agrees on passes both the consensus
and the bridge gate, so it appears in two sections — and that double count
made a fully translated page advertise, in the reader's own language, that it
was "showing in English".
"""
from app.models import (
    ConsensusAnalysis,
    Discussion,
    DiscussionTranslation,
    Statement,
    StatementTranslation,
    User,
    generate_slug,
)

NOTICE_EN = 'Translation in progress'
NOTICE_FR = 'Traduction en cours'


def _publishable_metadata():
    return {
        'stability_runs': 5,
        'stability_mean_ari': 0.80,
        'stability_consensus_jaccard_mean': 0.75,
    }


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _seed(db, *, translate_statements, translate_discussion, suffix):
    """One statement that is both a consensus statement and a bridge."""
    user = User(username=f'notice{suffix}', email=f'notice{suffix}@example.com',
                password='hashed-password')
    db.session.add(user)
    db.session.flush()
    discussion = Discussion(
        title=f'Notice Discussion {suffix}',
        slug=generate_slug(f'Notice Discussion {suffix}'),
        creator_id=user.id,
        has_native_statements=True,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(discussion)
    db.session.flush()

    both = Statement(
        discussion_id=discussion.id, user_id=user.id,
        content='A statement that is both a consensus statement and a bridge.',
        vote_count_agree=19, vote_count_disagree=1,
    )
    divisive = Statement(
        discussion_id=discussion.id, user_id=user.id,
        content='A statement that splits the two opinion groups apart.',
        vote_count_agree=10, vote_count_disagree=10,
    )
    db.session.add_all([both, divisive])
    db.session.flush()

    if translate_statements:
        db.session.add_all([
            StatementTranslation(statement_id=both.id, language_code='fr',
                                 content='FR-BRIDGE-CONSENSUS'),
            StatementTranslation(statement_id=divisive.id, language_code='fr',
                                 content='FR-DIVISIVE'),
        ])
    if translate_discussion:
        db.session.add(DiscussionTranslation(
            discussion_id=discussion.id, language_code='fr',
            title='FR-TITLE', description='FR-DESC',
        ))

    db.session.add(ConsensusAnalysis(
        discussion_id=discussion.id,
        num_clusters=2,
        silhouette_score=0.42,
        method='pca_kmeans',
        participants_count=12,
        statements_count=2,
        cluster_data={
            'cluster_assignments': {},
            'consensus_statements': [{
                'statement_id': both.id, 'agreement_rate': 0.95,
                'wilson_low': 0.80, 'wilson_high': 0.99, 'vote_count': 20,
            }],
            'bridge_statements': [{
                'statement_id': both.id, 'mean_agreement': 0.95,
                'min_cluster_agreement': 0.90, 'group_gap': 0.05,
                'polarity': 'agree', 'vote_count': 20,
                'wilson_low': 0.80, 'wilson_high': 0.99,
            }],
            'divisive_statements': [{
                'statement_id': divisive.id, 'group_gap': 0.84,
                'gap_ci_low': 0.52, 'gap_ci_high': 0.96,
                'p_value': 0.001, 'significant': True, 'vote_count': 20,
            }],
            'representative_statements': {},
            'pca_axis_loadings': {},
            'metadata': _publishable_metadata(),
        },
    ))
    db.session.commit()
    return discussion.id, user.id


def _bodies(client, discussion_id, lang=None):
    suffix = f'?lang={lang}' if lang else ''
    out = {}
    for name, path in (
        ('results', f'/discussions/{discussion_id}/consensus{suffix}'),
        ('report', f'/discussions/{discussion_id}/consensus/report{suffix}'),
    ):
        resp = client.get(path)
        assert resp.status_code == 200, f'{name} -> {resp.status_code}'
        out[name] = resp.get_data(as_text=True)
    return out


def _has_notice(body):
    return NOTICE_EN in body or NOTICE_FR in body


def test_no_notice_when_everything_is_translated(app, db, client):
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='full')

    _login(client, user_id)
    for name, body in _bodies(client, discussion_id, lang='fr').items():
        assert 'FR-BRIDGE-CONSENSUS' in body, name
        assert 'FR-DIVISIVE' in body, name
        assert 'FR-TITLE' in body, name
        assert not _has_notice(body), (
            f'{name}: every displayed statement and the title are translated, '
            'but the page still claims the translation is pending'
        )
        # The statement really does appear in two sections — the condition
        # that used to break the count.
        assert body.count('FR-BRIDGE-CONSENSUS') >= 2, name


def test_notice_when_a_statement_is_not_translated_yet(app, db, client):
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=False, translate_discussion=True, suffix='nostmt')

    _login(client, user_id)
    for name, body in _bodies(client, discussion_id, lang='fr').items():
        assert _has_notice(body), name
        assert 'both a consensus statement and a bridge' in body, name


def test_notice_when_the_discussion_title_is_not_translated_yet(app, db, client):
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=False, suffix='notitle')

    _login(client, user_id)
    for name, body in _bodies(client, discussion_id, lang='fr').items():
        assert _has_notice(body), name


def test_english_readers_never_see_the_notice(app, db, client):
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=False, translate_discussion=False, suffix='english')

    _login(client, user_id)
    for name, body in _bodies(client, discussion_id).items():
        assert not _has_notice(body), name
        assert 'both a consensus statement and a bridge' in body, name


def test_report_and_results_agree_on_the_notice(app, db, client):
    """The report is the printable view of the same data; it must not disagree
    with the page it was reached from."""
    for suffix, stmts, disc in (
        ('agreefull', True, True),
        ('agreepart', True, False),
        ('agreenone', False, False),
    ):
        with app.app_context():
            discussion_id, user_id = _seed(
                db, translate_statements=stmts, translate_discussion=disc,
                suffix=suffix)
        _login(client, user_id)
        bodies = _bodies(client, discussion_id, lang='fr')
        assert _has_notice(bodies['results']) == _has_notice(bodies['report']), suffix


def test_report_sets_the_language_cookie_like_the_results_page(app, db, client):
    """A reader landing on the report with ?lang=fr must not be thrown back to
    English by "Back to Analysis", which carries no ?lang= of its own.

    NOTE: this asserts the Set-Cookie header only. The cookie-driven *read*
    path is covered by the next test, and must be — see the harness caveat at
    the bottom of this module for why a second request in the same test
    cannot prove it.
    """
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='persist')

    _login(client, user_id)
    resp = client.get(f'/discussions/{discussion_id}/consensus/report?lang=fr')
    assert resp.status_code == 200
    assert any(
        c.startswith('ss_lang=fr') for c in resp.headers.getlist('Set-Cookie')
    ), 'the report did not persist the language preference'


def test_report_reads_the_language_from_the_cookie(app, db, client):
    """The cookie set above must actually drive the report's language.

    The cookie-driven request is deliberately the FIRST request this test
    makes — see the harness caveat at the bottom of this module.
    """
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='cookieread')

    _login(client, user_id)
    client.set_cookie('ss_lang', 'fr')
    body = client.get(f'/discussions/{discussion_id}/consensus/report').get_data(as_text=True)
    assert 'FR-TITLE' in body
    assert 'FR-BRIDGE-CONSENSUS' in body


def test_report_does_not_set_a_language_cookie_for_english(app, db, client):
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='noenlang')

    _login(client, user_id)
    resp = client.get(f'/discussions/{discussion_id}/consensus/report')
    assert not any(
        c.startswith('ss_lang=') for c in resp.headers.getlist('Set-Cookie')
    )


def test_report_is_noindex_with_a_canonical_to_the_analysis(app, db, client):
    """layout.html defaults to "index, follow". The report sits behind the
    participation gate and exists at several URLs (?print=, ?lang=) for the
    same content, so it must opt out and point at the indexable page."""
    import re

    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='robots')

    _login(client, user_id)
    html = client.get(f'/discussions/{discussion_id}/consensus/report').get_data(as_text=True)

    robots = re.findall(r'<meta\s+name="robots"[^>]*content="([^"]*)"', html)
    assert len(robots) == 1, f'expected exactly one robots tag, got {robots}'
    assert 'noindex' in robots[0]
    assert 'nofollow' not in robots[0]

    canonical = re.search(r'<link[^>]+rel="canonical"[^>]+href="([^"]+)"', html)
    assert canonical, 'report has no canonical'
    assert canonical.group(1).endswith(f'/discussions/{discussion_id}/consensus')

    # The analysis page itself stays indexable.
    results = client.get(f'/discussions/{discussion_id}/consensus').get_data(as_text=True)
    results_robots = re.findall(r'<meta\s+name="robots"[^>]*content="([^"]*)"', results)
    assert results_robots and 'noindex' not in results_robots[0]


# ── Harness caveat: one language per test function ───────────────────────
#
# Flask-Babel caches the resolved locale on ``g._flask_babel``, and ``g`` is
# bound to the *application* context. The ``app_context`` fixture pushes one
# app context for the whole test, so every ``client.get()`` in a single test
# function shares it: the first request's language sticks for all the rest,
# whatever ``?lang=`` or cookie the later ones carry.
#
# Production is unaffected — Flask pushes a fresh app context per request — but
# it means a test that switches language mid-function silently proves nothing.
# Assert one language per test function, and make the request you care about
# the first one.


def test_locale_is_pinned_per_test_function_not_per_request(app, db, client):
    """Pin the caveat above, so nobody writes a two-language test and trusts
    the result."""
    with app.app_context():
        discussion_id, user_id = _seed(
            db, translate_statements=True, translate_discussion=True, suffix='pinned')

    _login(client, user_id)
    first = client.get(f'/discussions/{discussion_id}/consensus/report').get_data(as_text=True)
    second = client.get(
        f'/discussions/{discussion_id}/consensus/report?lang=fr'
    ).get_data(as_text=True)

    assert 'FR-TITLE' not in first
    assert 'FR-TITLE' not in second, (
        'Flask-Babel no longer caches the locale on the app-context `g`. '
        'If this fails, the one-language-per-test rule documented above can '
        'be relaxed — and tests written around it should be revisited.'
    )
