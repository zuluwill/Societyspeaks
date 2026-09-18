"""Discussion search must qualify filters after the Programme join.

Sentry PYTHON-FLASK-JH: ``fetch_discussions`` used ``filter_by(topic=...)``
after ``outerjoin(Programme)``. Programme has no ``topic``, so the HTML
search 500ed. Programme *does* have ``country``, so the same ``filter_by``
silently filtered the programme row instead of the discussion.
"""

from app.models import Discussion, Programme, User, generate_slug


def _user(db, username='searcher'):
    user = User(username=username, email=f'{username}@example.com', password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _discussion(db, *, title, creator_id, topic=None, country=None, city=None, programme_id=None):
    discussion = Discussion(
        title=title,
        slug=generate_slug(title),
        description=f'Description for {title} that is long enough.',
        creator_id=creator_id,
        geographic_scope='country' if country else 'global',
        topic=topic,
        country=country,
        city=city,
        programme_id=programme_id,
    )
    db.session.add(discussion)
    db.session.flush()
    return discussion


def test_search_page_topic_filter_does_not_500(client, db):
    creator = _user(db)
    match = _discussion(
        db,
        title='Tech search match',
        creator_id=creator.id,
        topic='Technology',
        country='Japan',
    )
    other = _discussion(db, title='Health search other', creator_id=creator.id, topic='Healthcare')
    db.session.commit()

    response = client.get('/discussions/search?topic=Technology&country=Japan&sort=popular')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert match.title in body
    assert other.title not in body


def test_search_page_country_filters_discussion_not_programme(client, db):
    creator = _user(db, 'countrysearch')
    japan_programme = Programme(
        name='Japan programme',
        slug=generate_slug('Japan programme'),
        creator_id=creator.id,
        country='Japan',
        status='active',
        visibility='public',
    )
    db.session.add(japan_programme)
    db.session.flush()

    uk_in_japan_programme = _discussion(
        db,
        title='UK discussion on Japan programme',
        creator_id=creator.id,
        topic='Technology',
        country='United Kingdom',
        programme_id=japan_programme.id,
    )
    japan_standalone = _discussion(
        db,
        title='Japan standalone discussion',
        creator_id=creator.id,
        topic='Technology',
        country='Japan',
    )
    db.session.commit()

    response = client.get('/discussions/search?topic=Technology&country=Japan')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert japan_standalone.title in body
    assert uk_in_japan_programme.title not in body


def test_search_page_city_filter_does_not_500(client, db):
    creator = _user(db, 'citysearch')
    tokyo = _discussion(
        db,
        title='Tokyo city discussion',
        creator_id=creator.id,
        topic='Society',
        country='Japan',
        city='Tokyo',
    )
    other = _discussion(
        db,
        title='Osaka city discussion',
        creator_id=creator.id,
        topic='Society',
        country='Japan',
        city='Osaka',
    )
    db.session.commit()

    response = client.get('/discussions/search?city=Tokyo')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert tokyo.title in body
    assert other.title not in body
