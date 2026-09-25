"""Homepage rail ranks open native discussions by recent voters."""

from datetime import timedelta

from app.lib.time import utcnow_naive
from app.models import Discussion, Programme, Statement, StatementVote, generate_slug
from app import cache


def _discussion(db, title, **kwargs):
    defaults = dict(
        title=title,
        slug=generate_slug(title)[:140],
        has_native_statements=True,
        geographic_scope='global',
        partner_env='live',
        is_closed=False,
        topic='Society',
    )
    defaults.update(kwargs)
    discussion = Discussion(**defaults)
    db.session.add(discussion)
    db.session.flush()
    return discussion


def _statement(db, discussion, content):
    statement = Statement(
        discussion_id=discussion.id,
        content=content,
        mod_status=1,
        is_deleted=False,
    )
    db.session.add(statement)
    db.session.flush()
    return statement


def _vote(db, discussion, statement, fingerprint, *, when=None):
    vote = StatementVote(
        statement_id=statement.id,
        discussion_id=discussion.id,
        session_fingerprint=fingerprint,
        vote=1,
    )
    if when is not None:
        vote.created_at = when
    db.session.add(vote)


def test_featured_prefers_recent_native_voters_over_polis_pin(app, db):
    cache.delete('featured_discussions_v2_6')
    now = utcnow_naive()

    polis = _discussion(
        db,
        'How should we improve the NHS?',
        has_native_statements=False,
        is_featured=True,
        topic='Healthcare',
        embed_code='<iframe src="https://pol.is/nhs"></iframe>',
        created_at=now - timedelta(days=700),
    )
    quiet = _discussion(db, 'A quiet native discussion', topic='Education')
    _statement(db, quiet, 'A visible claim with no votes yet, long enough to store.')

    active = _discussion(db, 'People are voting on housing', topic='Economy')
    active_statement = _statement(
        db, active, 'Councils should build homes on public land near stations.'
    )
    _vote(db, active, active_statement, 'voter-a', when=now - timedelta(days=1))
    _vote(db, active, active_statement, 'voter-b', when=now - timedelta(days=2))

    older = _discussion(db, 'Last month climate votes', topic='Environment')
    older_statement = _statement(
        db, older, 'New fossil fuel licences should stop this decade.'
    )
    _vote(db, older, older_statement, 'voter-c', when=now - timedelta(days=40))

    protest = _discussion(db, 'Protest rights in city centres', topic='Politics')
    protest_statement = _statement(
        db, protest, 'Peaceful protest should not need prior police permission.'
    )
    _vote(db, protest, protest_statement, 'voter-protest', when=now - timedelta(hours=4))

    fixture = _discussion(db, 'Test fixture discussion', topic='Society')
    fixture_statement = _statement(
        db, fixture, 'This row is a fixture and must stay off the homepage.'
    )
    _vote(db, fixture, fixture_statement, 'voter-fixture', when=now)

    culture = _discussion(db, 'Museum funding this week', topic='Culture')
    culture_statement = _statement(
        db, culture, 'National museums should stay free to enter.'
    )
    _vote(db, culture, culture_statement, 'voter-e', when=now - timedelta(hours=5))

    same_topic = _discussion(db, 'A second economy discussion', topic='Economy')
    same_statement = _statement(
        db, same_topic, 'Rent caps should apply to new tenancies in cities.'
    )
    _vote(db, same_topic, same_statement, 'voter-d', when=now - timedelta(hours=3))

    db.session.commit()

    featured = Discussion.get_featured(limit=4)
    titles = [d.title for d in featured]

    assert polis.title not in titles
    assert fixture.title not in titles
    assert protest.title in titles
    assert titles[0] == active.title
    assert older.title in titles
    assert same_topic.title not in titles
    assert active.public_participant_count == 2


def test_featured_skips_closed_and_private_programme_discussions(app, db):
    cache.delete('featured_discussions_v2_6')
    now = utcnow_naive()

    closed = _discussion(db, 'Closed native discussion', is_closed=True, topic='Politics')
    closed_statement = _statement(db, closed, 'This discussion no longer accepts votes from anyone.')
    _vote(db, closed, closed_statement, 'voter-closed', when=now)

    private = Programme(
        name='Private programme',
        slug='private-programme-featured',
        status='active',
        visibility='private',
    )
    db.session.add(private)
    db.session.flush()
    hidden = _discussion(
        db,
        'Hidden programme discussion',
        programme_id=private.id,
        topic='Healthcare',
    )
    hidden_statement = _statement(db, hidden, 'Only programme members should see this claim.')
    _vote(db, hidden, hidden_statement, 'voter-hidden', when=now)

    public = _discussion(db, 'Open public discussion', topic='Culture')
    public_statement = _statement(db, public, 'Libraries should stay open on Sundays in every town.')
    _vote(db, public, public_statement, 'voter-public', when=now)
    db.session.commit()

    titles = [d.title for d in Discussion.get_featured(limit=3)]
    assert titles == [public.title]


def test_homepage_rail_uses_popular_native_discussions(app, db, client):
    cache.delete('featured_discussions_v2_6')
    now = utcnow_naive()
    _discussion(
        db,
        'How should we improve the NHS?',
        has_native_statements=False,
        is_featured=True,
        topic='Healthcare',
        embed_code='<iframe src="https://pol.is/nhs"></iframe>',
    )
    popular = _discussion(db, 'Voters gathered on transit', topic='Infrastructure')
    statement = _statement(db, popular, 'Cities should fund frequent buses before new roads.')
    _vote(db, popular, statement, 'home-voter', when=now)
    db.session.commit()

    html = client.get('/').get_data(as_text=True)
    assert 'The discussions people are voting on right now.' in html
    assert 'Voters gathered on transit' in html
    assert '1 person has voted' in html
    assert 'How should we improve the NHS?' not in html
