"""
Rendered-markup regressions for pages where HTML leaked out as visible text,
counters pushed the layout around, or a figure printed twice.

These must be *render* assertions, not source greps: both newstyle-gettext
traps (an escaped interpolated param, and `~` escaping a string literal under
autoescape) look correct in the template source and only surface once the
page is rendered.
"""
import json
import re

from app.models import Discussion, Statement, User, generate_slug


def _render(client, path):
    resp = client.get(path)
    assert resp.status_code == 200, f"{path} -> {resp.status_code}"
    return resp.get_data(as_text=True)


# ── Escaped anchor markup in gettext params ──────────────────────────────

def test_publisher_hub_renders_real_links_not_escaped_markup(client, db):
    html = _render(client, '/for-publishers/')
    assert '&lt;a href=' not in html, (
        'anchor markup leaked as visible text — an interpolated gettext param '
        'was a plain str, so Markup.__mod__ escaped it'
    )
    assert re.search(
        r'Get <code>\{id\}</code> from the <a href="[^"]+"[^>]*>Lookup API</a>',
        html,
    ), 'the Lookup API link did not render as an anchor'
    assert '>embed generator</a>' in html


def test_embed_generator_renders_real_links_not_escaped_markup(client, db):
    html = _render(client, '/for-publishers/embed')
    assert '&lt;a href=' not in html
    assert '>Partner Portal</a>' in html
    assert '>API Reference</a>' in html


def test_no_template_passes_concatenated_anchor_markup_to_gettext():
    """Guard the anti-pattern at source too: `'<a href="' ~ url_for(...)`
    inside a gettext param can never render as a link."""
    import pathlib

    offenders = []
    for path in pathlib.Path('app/templates').rglob('*.html'):
        text = path.read_text(encoding='utf-8')
        if re.search(r"""=\s*'<a\s+href=["']?\s*'\s*~""", text):
            offenders.append(str(path))
    assert offenders == [], (
        f'templates building anchors by `~` concatenation: {offenders}. '
        'Use {% set link %}<a …>…</a>{% endset %} instead.'
    )


# ── Character counter layout ─────────────────────────────────────────────

def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_statement_form_counter_cannot_push_the_layout(app, db, client):
    with app.app_context():
        user = User(username='counteruser', email='counter@example.com',
                    password='hashed-password')
        db.session.add(user)
        db.session.flush()
        discussion = Discussion(
            title='Counter Layout Discussion',
            slug=generate_slug('Counter Layout Discussion'),
            creator_id=user.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.commit()
        discussion_id, user_id = discussion.id, user.id

    _login(client, user_id)
    html = _render(client, f'/discussions/{discussion_id}/statements/create')

    counter = re.search(r'<div id="charCount" class="([^"]+)"', html)
    assert counter, 'character counter element missing'
    classes = counter.group(1).split()
    # Reserved width + tabular figures: the counter must not resize as the
    # count grows, or the row re-wraps and the form jumps under the cursor.
    assert 'tabular-nums' in classes
    assert 'shrink-0' in classes
    assert any(c.startswith('w-') for c in classes)

    # A gap between the hint and the counter, so they cannot abut on narrow
    # viewports.
    row = re.search(r'<div class="([^"]*justify-between[^"]*)">\s*<div class="text-sm text-gray-500">', html)
    assert row, 'counter row wrapper missing'
    assert 'gap-x-' in row.group(1)
    assert 'flex-wrap' in row.group(1)

    # Colour-only state changes: a font-weight swap changed the counter's
    # width on every threshold crossing.
    assert 'font-semibold"' not in re.search(
        r'currentCount\.className = .*?;\s*\}', html, re.S
    ).group(0)


# ── Embed vote total ─────────────────────────────────────────────────────

def test_embed_prints_the_vote_total_once(app, db, client):
    with app.app_context():
        user = User(username='embedtotals', email='embedtotals@example.com',
                    password='hashed-password')
        db.session.add(user)
        db.session.flush()
        discussion = Discussion(
            title='Embed Totals Discussion',
            slug=generate_slug('Embed Totals Discussion'),
            creator_id=user.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        db.session.add(Statement(
            discussion_id=discussion.id,
            user_id=user.id,
            content='A statement with a distinctive vote total for this test.',
            vote_count_agree=100,
            vote_count_disagree=80,
            vote_count_unsure=51,
        ))
        db.session.commit()
        discussion_id = discussion.id

    html = _render(client, f'/discussions/{discussion_id}/embed')

    stats = re.search(r'<div class="vote-stats"[^>]*>(.*?)</div>', html, re.S)
    assert stats, 'vote-stats block missing'
    assert stats.group(1).count('231') == 1, (
        f'vote total printed more than once: {stats.group(1)!r}'
    )
    assert '231 total votes' in re.sub(r'\s+', ' ', stats.group(1))

    # The JS updater must not re-append the count either: the format string
    # already contains it.
    js = re.search(
        r"totalSpan\.className = 'total-votes';(.*?)statsEl\.appendChild\(totalSpan\);",
        html, re.S,
    )
    assert js, 'vote-stats updater missing'
    assert 'totalVotesLabel' in js.group(1)
    assert 'totalSpan.textContent = total;' not in js.group(1)


def _embed_with_votes(app, db, agree, disagree, unsure, suffix=''):
    with app.app_context():
        user = User(
            username=f'embedvotes{suffix}',
            email=f'embedvotes{suffix}@example.com',
            password='hashed-password',
        )
        db.session.add(user)
        db.session.flush()
        discussion = Discussion(
            title=f'Embed Votes {suffix}',
            slug=generate_slug(f'Embed Votes {suffix}'),
            creator_id=user.id,
            has_native_statements=True,
            topic='Society',
            geographic_scope='global',
        )
        db.session.add(discussion)
        db.session.flush()
        db.session.add(Statement(
            discussion_id=discussion.id,
            user_id=user.id,
            content='A statement whose vote total is checked for plural form.',
            vote_count_agree=agree,
            vote_count_disagree=disagree,
            vote_count_unsure=unsure,
        ))
        db.session.commit()
        return discussion.id


def _vote_stats(html):
    block = re.search(r'<div class="vote-stats"[^>]*>(.*?)</div>', html, re.S)
    assert block, 'vote-stats block missing'
    return re.sub(r'\s+', ' ', block.group(1)).strip()


def test_embed_vote_total_uses_singular_and_plural(app, db, client):
    one = _embed_with_votes(app, db, 1, 0, 0, suffix='one')
    many = _embed_with_votes(app, db, 100, 80, 51, suffix='many')

    singular = _vote_stats(_render(client, f'/discussions/{one}/embed'))
    assert '1 total vote<' in singular or '1 total vote ' in singular
    assert 'total votes' not in singular

    plural = _vote_stats(_render(client, f'/discussions/{many}/embed'))
    assert '231 total votes' in plural
    assert plural.count('231') == 1


def test_embed_js_resolves_plural_forms_from_the_catalog(app, db, client):
    """`gettext('%(n)d total votes')` cannot translate — a msgid_plural is not
    a lookup key — so the client would show English in every locale. The JS
    catalog must carry catalog-resolved forms keyed by CLDR category."""
    did = _embed_with_votes(app, db, 5, 2, 1, suffix='js')
    html = _render(client, f'/discussions/{did}/embed')

    forms_src = re.search(r'totalVotesForms: (\{.*?\}),', html)
    assert forms_src, 'totalVotesForms missing from the JS catalog'
    forms = json.loads(forms_src.group(1))
    assert forms['one'] == '%(n)d total vote'
    assert forms['other'] == '%(n)d total votes'
    # No singular gettext of a plural msgid left behind.
    assert "gettext_js('%(n)d total votes')" not in html
    assert 'totalVotesFmt' not in html
    # The browser picks the category; no plural-rule eval (CSP has no
    # unsafe-eval).
    assert 'Intl.PluralRules' in html
    assert 'new Function' not in html


def test_embed_js_emits_every_plural_category_for_arabic(app, db, client):
    """Arabic has six CLDR categories. A hard-coded `n === 1` split would be
    wrong for five of them."""
    did = _embed_with_votes(app, db, 3, 1, 0, suffix='ar')
    html = _render(client, f'/discussions/{did}/embed?lang=ar')
    forms = json.loads(re.search(r'totalVotesForms: (\{.*?\}),', html).group(1))
    assert {'zero', 'one', 'two', 'few', 'many', 'other'} <= set(forms)
    assert re.search(r'lang: "ar"', html)


def test_plural_category_probes_cover_each_supported_locale():
    """Every supported locale must resolve a usable category set, and the
    sweep must be cached — it runs on every embed render otherwise."""
    from app import _plural_category_probes
    from app.lib.locale_utils import SUPPORTED_LANGUAGES

    for code in SUPPORTED_LANGUAGES:
        probes = _plural_category_probes(code)
        assert probes, code
        assert 'other' in probes or 'one' in probes, code
        # Representative counts must actually belong to their category.
        from babel import Locale
        locale = Locale.parse(code)
        for category, n in probes.items():
            assert locale.plural_form(n) == category, (code, category, n)

    assert _plural_category_probes('ar').keys() >= {
        'zero', 'one', 'two', 'few', 'many', 'other'
    }
    assert set(_plural_category_probes('ja')) == {'other'}
    # Unknown locale tags fall back instead of raising.
    assert _plural_category_probes('not-a-locale')

    info = _plural_category_probes.cache_info()
    assert info.hits > 0, 'probe sweep is not being cached'
