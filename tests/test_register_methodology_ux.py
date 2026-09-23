"""Register and methodology pages should stay light and usable."""


def test_register_page_explains_why_and_skips_unused_scripts(client):
    response = client.get('/auth/register')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Create your account' in body
    assert 'Save your votes' in body
    assert 'At least 8 characters' in body
    assert 'name="verification"' in body
    assert 'id="register-email"' in body
    assert 'disable_surveys: true' in body
    assert 'js/vote-resilience.js' not in body
    assert 'js/brief-audio.js' not in body
    assert 'js/toast.js' in body


def test_methodology_collapses_source_list_and_skips_unused_scripts(client):
    response = client.get('/brief/methodology')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'Browse the 140+ sources' in body
    assert '<details' in body
    assert 'The Guardian' in body
    assert 'disable_surveys: true' in body
    assert 'js/vote-resilience.js' not in body
    assert 'js/brief-audio.js' not in body
    assert 'js/toast.js' in body


def test_login_also_disables_surveys(client):
    response = client.get('/auth/login')
    body = response.get_data(as_text=True)

    assert response.status_code == 200
    assert 'disable_surveys: true' in body
    assert 'js/vote-resilience.js' not in body
    assert 'id="login-email"' in body
    assert 'id="login-password"' in body
    assert 'data-password-toggle="login-password"' in body


def test_register_keeps_values_after_validation_error(client):
    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7

    response = client.post(
        '/auth/register',
        data={
            'username': 'keepme',
            'email': 'keepme@example.com',
            'password': 'short',
            'verification': '7',
        },
        follow_redirects=False,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'value="keepme"' in body
    assert 'value="keepme@example.com"' in body
    assert 'at least 8 characters' in body.lower()


def test_register_rejects_taken_username(app, db, client):
    from app.models import User

    db.session.add(User(username='takenname', email='taken@example.com', password='hashed'))
    db.session.commit()

    with client.session_transaction() as sess:
        sess['captcha_expected'] = 7

    response = client.post(
        '/auth/register',
        data={
            'username': 'TakenName',
            'email': 'newperson@example.com',
            'password': 'ValidPass123!',
            'verification': '7',
        },
        follow_redirects=False,
    )
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'already taken' in body.lower()
    assert User.query.filter_by(email='newperson@example.com').first() is None


def test_register_shows_invitation_and_prefills_email(client):
    with client.session_transaction() as sess:
        sess['pending_invitation_org'] = 'Civic Lab'
        sess['pending_invitation_email'] = 'invitee@example.com'

    response = client.get('/auth/register')
    body = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'Civic Lab' in body
    assert 'value="invitee@example.com"' in body
    assert 'readonly' in body


def test_methodology_source_list_is_in_a_partial(client):
    response = client.get('/brief/methodology')
    body = response.get_data(as_text=True)
    assert 'content-visibility: auto' in body
    assert 'methodology-source-chevron' in body
    assert 'The Guardian' in body
