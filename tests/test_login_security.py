"""Login rate-limiting and enumeration-safety (uses a real limiter, unlike the shared
`app` fixture which disables it)."""

import os
import tempfile

import pytest

from onboarding_crm import create_app
from onboarding_crm.extensions import db as _db
from onboarding_crm.models import User
from werkzeug.security import generate_password_hash


@pytest.fixture
def rl_client():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.environ['DATABASE_URL'] = f'sqlite:///{path}'
    app = create_app()
    app.config.update(TESTING=True, WTF_CSRF_ENABLED=False)  # limiter stays ENABLED
    with app.app_context():
        _db.create_all()
        _db.session.add(User(username='u', password=generate_password_hash('pw'),
                             role='mentor', department='product', is_active=True))
        _db.session.commit()
    yield app.test_client()
    with app.app_context():
        _db.session.remove()
        _db.drop_all()
    os.close(fd)
    os.unlink(path)


def test_login_is_rate_limited(rl_client):
    codes = [rl_client.post('/login', data={'login': 'u', 'password': 'bad'}).status_code
             for _ in range(8)]
    assert codes[0] == 401
    assert 429 in codes  # the limit trips within the window


def test_unknown_user_returns_401_not_500(rl_client):
    # Exercises the dummy-hash path — must not raise on a missing user.
    r = rl_client.post('/login', data={'login': 'ghost', 'password': 'x'})
    assert r.status_code == 401
