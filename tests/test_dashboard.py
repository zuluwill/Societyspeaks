import re

from app.models import (
    User,
    Discussion,
    DiscussionView,
    IndividualProfile,
    CompanyProfile,
    ProfileView,
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


def _assert_dashboard_stat(body, label, value):
    # Match stat label followed by the value paragraph; tolerates responsive size classes
    pattern = rf"{re.escape(label)}</p>\s*<p class=\"[^\"]*font-bold text-gray-800[^\"]*\">{value}</p>"
    assert re.search(pattern, body), f"Expected {label} stat to equal {value}"


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
    _assert_dashboard_stat(body, 'Discussions', 8)
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
    _assert_dashboard_stat(body, 'Discussion Views', 8)


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
    _assert_dashboard_stat(body, 'Programmes', 0)
    _assert_dashboard_stat(body, 'Discussions', 0)
    _assert_dashboard_stat(body, 'Discussion Views', 0)
    _assert_dashboard_stat(body, 'Profile Views', 0)
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


def test_dashboard_profile_views_only_count_active_profile_type(app, db):
    with app.app_context():
        indiv_user = _create_user(db, 'indiv_profile_views', 'indiv_profile_views@example.com')
        indiv_user.profile_type = 'individual'
        indiv_profile = IndividualProfile(
            user_id=indiv_user.id,
            full_name='Ada Lovelace',
            slug=generate_slug('Ada Lovelace'),
        )
        db.session.add(indiv_profile)
        db.session.flush()

        company_user = _create_user(db, 'company_profile_views', 'company_profile_views@example.com')
        company_user.profile_type = 'company'
        company_profile = CompanyProfile(
            user_id=company_user.id,
            company_name='Overlap Corp',
            slug=generate_slug('Overlap Corp'),
        )
        db.session.add(company_profile)
        db.session.flush()

        # Add a view for the company profile only. This should never count
        # toward the individual user's profile view total.
        db.session.add(ProfileView(company_profile_id=company_profile.id, viewer_id=company_user.id))
        db.session.commit()
        indiv_user_id = indiv_user.id

    client = app.test_client()
    _login(client, indiv_user_id)
    resp = client.get('/auth/dashboard')
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    _assert_dashboard_stat(body, 'Profile Views', 0)
