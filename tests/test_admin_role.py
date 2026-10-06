"""Admin role = "template steward": shares the devops TEMPLATE workflow with the
developer, but NOT the destructive/account powers (hard purge, user management,
creating users). Those stay developer-only."""

from werkzeug.security import generate_password_hash

from onboarding_crm.extensions import db
from onboarding_crm.models import User, OnboardingTemplate


def _mk_admin(app):
    with app.app_context():
        u = User(username='admin_t', password=generate_password_hash('pw'),
                 role='admin', department=None, is_active=True)
        db.session.add(u)
        db.session.commit()
        return u.id


# ── what admin CAN do ────────────────────────────────────────────────────────

def test_admin_sees_devops_template_cabinet(app, client, login):
    login(_mk_admin(app))
    for path in ['/devops/library', '/devops/onboardings', '/devops/trash',
                 '/dashboard/developer?tab=overview', '/dashboard/developer?tab=departments']:
        assert client.get(path).status_code == 200, path


def test_admin_can_create_and_soft_delete_library_template(app, client, login):
    login(_mk_admin(app))
    assert client.post('/devops/library/new', data={'name': 'Lib by admin'}).status_code in (302, 303)
    with app.app_context():
        t = OnboardingTemplate.query.filter_by(name='Lib by admin').first()
        assert t is not None and t.is_library is True
        tid = t.id
    assert client.post(f'/devops/library/{tid}/delete').status_code in (302, 303)
    with app.app_context():
        assert OnboardingTemplate.query.get(tid).is_archived is True


def test_admin_can_restore_from_trash(app, client, login):
    login(_mk_admin(app))
    with app.app_context():
        t = OnboardingTemplate(name='arch', structure={'blocks': []}, is_library=True, is_archived=True)
        db.session.add(t)
        db.session.commit()
        tid = t.id
    assert client.post(f'/devops/trash/template/{tid}/restore').status_code in (302, 303)
    with app.app_context():
        assert OnboardingTemplate.query.get(tid).is_archived is False


# ── what admin CANNOT do (developer-only) ────────────────────────────────────

def test_admin_users_tab_is_redirected_away(app, client, login):
    login(_mk_admin(app))
    r = client.get('/dashboard/developer?tab=users&view=all', follow_redirects=False)
    assert r.status_code in (301, 302)


def test_admin_cannot_create_users(app, client, login):
    login(_mk_admin(app))
    r = client.post('/dashboard/developer',
                    data={'role': 'manager', 'username': 'x', 'password': 'y'})
    assert r.status_code == 403


def test_admin_cannot_purge_from_trash(app, client, login):
    login(_mk_admin(app))
    with app.app_context():
        t = OnboardingTemplate(name='arch2', structure={'blocks': []}, is_library=True, is_archived=True)
        db.session.add(t)
        db.session.commit()
        tid = t.id
    assert client.post(f'/devops/trash/template/{tid}/purge').status_code == 403
    with app.app_context():
        assert OnboardingTemplate.query.get(tid) is not None  # not deleted


def test_admin_cannot_manage_accounts(app, client, login, users):
    login(_mk_admin(app))
    mid = users['manager_of_a']
    assert client.post(f'/dashboard/developer/user/{mid}/delete').status_code == 403
    assert client.post(f'/dashboard/developer/user/{mid}/toggle_active').status_code == 403
    assert client.post(f'/dashboard/developer/user/{mid}/reset_password',
                       data={'new_password': 'zzz'}).status_code == 403
