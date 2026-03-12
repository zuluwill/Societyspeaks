from app.models import CompanyProfile, IndividualProfile, User


def _create_user(db, username, email):
    user = User(username=username, email=email, password='hashed-password')
    db.session.add(user)
    db.session.flush()
    return user


def _login(client, user_id):
    with client.session_transaction() as sess:
        sess['_user_id'] = str(user_id)
        sess['_fresh'] = True


def test_create_individual_profile_redirects_to_dashboard(app, db):
    with app.app_context():
        user = _create_user(db, 'new_individual', 'new_individual@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        '/profiles/profile/individual/new',
        data={
            'full_name': 'New Individual User',
            'city': 'London',
            'country': 'UK',
            'email': 'new_individual@example.com',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/auth/dashboard')

    with app.app_context():
        created = IndividualProfile.query.filter_by(user_id=user_id).first()
        assert created is not None
        refreshed_user = db.session.get(User, user_id)
        assert refreshed_user.profile_type == 'individual'


def test_create_company_profile_redirects_to_dashboard(app, db):
    with app.app_context():
        user = _create_user(db, 'new_org', 'new_org@example.com')
        db.session.commit()
        user_id = user.id

    client = app.test_client()
    _login(client, user_id)
    response = client.post(
        '/profiles/profile/company/new',
        data={
            'company_name': 'New Org Ltd',
            'city': 'London',
            'country': 'UK',
            'email': 'new_org@example.com',
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/auth/dashboard')

    with app.app_context():
        created = CompanyProfile.query.filter_by(user_id=user_id).first()
        assert created is not None
        refreshed_user = db.session.get(User, user_id)
        assert refreshed_user.profile_type == 'company'
