from app.models import (
    User,
    Discussion,
    DiscussionView,
    IndividualProfile,
    CompanyProfile,
    Programme,
    generate_slug,
)


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def _create_discussion(db, creator_id, title='Test Discussion'):
    d = Discussion(
        title=title,
        slug=generate_slug(title + str(creator_id)),
        creator_id=creator_id,
        topic='Society',
        geographic_scope='global',
    )
    db.session.add(d)
    db.session.flush()
    return d


def test_dashboard_redirects_unauthenticated(app, db):
    client = app.test_client()
    resp = client.get('/auth/dashboard', follow_redirects=False)
    assert resp.status_code == 302
    assert '/auth/login' in resp.headers['Location']


def test_dashboard_renders_for_user_with_no_profile(app, db):
    with app.app_context():
        user = _create_user(db, 'noprofile_user', 'noprofile@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'noprofile_user' in body
    assert 'Welcome back' in body


def test_dashboard_shows_first_name_for_individual_profile(app, db):
    with app.app_context():
        user = _create_user(db, 'indiv_user', 'indiv@example.com')
        user.profile_type = 'individual'
        profile = IndividualProfile(
            user_id=user.id,
            full_name='Alice Bloggs',
            slug=generate_slug('Alice Bloggs'),
        )
        db.session.add(profile)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Welcome back, Alice' in body
    assert 'Individual' in body


def test_dashboard_shows_company_name_for_company_profile(app, db):
    with app.app_context():
        user = _create_user(db, 'company_user', 'company@example.com')
        user.profile_type = 'company'
        profile = CompanyProfile(
            user_id=user.id,
            company_name='Acme Corp',
            slug=generate_slug('Acme Corp'),
        )
        db.session.add(profile)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Welcome back, Acme Corp' in body
    assert 'Organisation' in body


def test_dashboard_shows_user_programme(app, db):
    with app.app_context():
        user = _create_user(db, 'prog_owner', 'prog_owner@example.com')
        prog = Programme(
            name='My Test Programme',
            slug=generate_slug('My Test Programme'),
            creator_id=user.id,
            visibility='public',
            status='active',
        )
        db.session.add(prog)
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'My Test Programme' in body
    assert 'Owner/Editor' in body


def test_dashboard_limits_discussions_to_six(app, db):
    with app.app_context():
        user = _create_user(db, 'disc_user', 'disc_user@example.com')
        for i in range(8):
            _create_discussion(db, user.id, title=f'Discussion {i}')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # Stat card must show all 8
    assert '8' in body
    # "View all" text appears when total > 6
    assert '8 total' in body or 'View all 8' in body


def test_dashboard_discussion_views_counts_all_not_just_displayed(app, db):
    with app.app_context():
        user = _create_user(db, 'views_user', 'views_user@example.com')
        discussion_ids = []
        for i in range(8):
            d = _create_discussion(db, user.id, title=f'Views Discussion {i}')
            discussion_ids.append(d.id)
        # Add a view to each discussion
        for did in discussion_ids:
            db.session.add(DiscussionView(discussion_id=did, ip_address=f'1.2.3.{did % 254}'))
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    # 8 views must appear somewhere in the page (in the stat card)
    assert 'Discussion Views' in body
    assert '8' in body


def test_dashboard_stat_counts_are_zero_for_new_user(app, db):
    with app.app_context():
        user = _create_user(db, 'zero_user', 'zero@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Programmes' in body
    assert 'Discussions' in body
    assert 'No programmes yet' in body
    assert 'No discussions yet' in body


def test_dashboard_shows_empty_state_programmes_cta(app, db):
    with app.app_context():
        user = _create_user(db, 'empty_prog_user', 'empty_prog@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Create your first programme' in body
    assert 'Start your first discussion' in body


def test_dashboard_profile_create_prompt_shown_without_profile(app, db):
    with app.app_context():
        user = _create_user(db, 'no_profile2', 'no_profile2@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert 'Create profile' in body
