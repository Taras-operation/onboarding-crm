import os
import tempfile

import pytest

# create_app() requires these before it is imported/called.
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('SESSION_COOKIE_SECURE', 'false')

from onboarding_crm import create_app
from onboarding_crm.extensions import db as _db
from onboarding_crm.models import User
from werkzeug.security import generate_password_hash


@pytest.fixture
def app():
    fd, path = tempfile.mkstemp(suffix='.db')
    os.environ['DATABASE_URL'] = f'sqlite:///{path}'
    application = create_app()
    application.config.update(
        TESTING=True,
        WTF_CSRF_ENABLED=False,
        RATELIMIT_ENABLED=False,  # per-test rate limits would cause flaky 429s
    )
    with application.app_context():
        _db.create_all()
    yield application
    with application.app_context():
        _db.session.remove()
        _db.drop_all()
    os.close(fd)
    os.unlink(path)


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    """Log a client in as a user id without going through the password flow."""
    def _login(user_id):
        with client.session_transaction() as sess:
            sess['_user_id'] = str(user_id)
    return _login


def _mk(role, username, dept='product', added_by=None, active=True, password='pw'):
    u = User(
        username=username,
        password=generate_password_hash(password),
        role=role,
        department=dept,
        added_by_id=added_by,
        is_active=active,
    )
    _db.session.add(u)
    _db.session.commit()
    return u


@pytest.fixture
def users(app):
    """A small org, returned as a name -> id map (ids are safe outside the app context):

        teamlead ─┬─ mentor_a ── manager_of_a
                  └─ mentor_b ── manager_of_b
        developer (global), head (department-wide)
    """
    with app.app_context():
        developer = _mk('developer', 'dev', dept=None)
        teamlead = _mk('teamlead', 'tl')
        head = _mk('head', 'head')
        mentor_a = _mk('mentor', 'mentorA', added_by=teamlead.id)
        mentor_b = _mk('mentor', 'mentorB', added_by=teamlead.id)
        manager_of_a = _mk('manager', 'mgrA', added_by=mentor_a.id)
        manager_of_b = _mk('manager', 'mgrB', added_by=mentor_b.id)
        return {
            'developer': developer.id,
            'teamlead': teamlead.id,
            'head': head.id,
            'mentor_a': mentor_a.id,
            'mentor_b': mentor_b.id,
            'manager_of_a': manager_of_a.id,
            'manager_of_b': manager_of_b.id,
        }


@pytest.fixture
def make_instance(app):
    """Factory: create an OnboardingInstance for a manager id with N stage blocks."""
    from onboarding_crm.models import OnboardingInstance

    def _make(manager_id, mentor_id, stages=2, step=0, archived=False):
        blocks = [{'type': 'stage', 'title': f'S{i}'} for i in range(stages)]
        with app.app_context():
            inst = OnboardingInstance(
                name='o', manager_id=manager_id, mentor_id=mentor_id,
                structure={'blocks': blocks}, onboarding_step=step, archived=archived,
            )
            _db.session.add(inst)
            _db.session.commit()
            return inst.id
    return _make


@pytest.fixture
def make_template(app):
    from onboarding_crm.models import OnboardingTemplate

    def _make(created_by, dept='product', is_global=False):
        with app.app_context():
            tpl = OnboardingTemplate(
                name='tpl', structure={'blocks': []},
                created_by=created_by, department=dept, is_global=is_global,
            )
            _db.session.add(tpl)
            _db.session.commit()
            return tpl.id
    return _make
