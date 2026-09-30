"""Кошик (soft delete): deleting a template/user archives it; from the trash a devops
either restores it or purges it from the DB. Everything runs on the fixture's temp DB."""

from onboarding_crm.extensions import db
from onboarding_crm.models import User, OnboardingTemplate, OnboardingInstance
from onboarding_crm.permissions import managers_query_for


# ── templates ──────────────────────────────────────────────────────────────

def test_library_delete_archives_instead_of_hard_delete(app, client, login, users):
    login(users['developer'])
    with app.app_context():
        tpl = OnboardingTemplate(name='L1', structure={'blocks': []}, is_library=True,
                                 created_by=users['developer'], department=None)
        db.session.add(tpl)
        db.session.commit()
        tid = tpl.id

    r = client.post(f'/devops/library/{tid}/delete', follow_redirects=False)
    assert r.status_code in (302, 303)

    with app.app_context():
        tpl = OnboardingTemplate.query.get(tid)
        assert tpl is not None, 'row must survive (soft delete)'
        assert tpl.is_archived is True
        assert tpl.archived_at is not None

    # hidden from the library list, shown in the trash
    assert f'/devops/library/{tid}'.encode() not in client.get('/devops/library').data
    assert b'L1' in client.get('/devops/trash').data


def test_trash_restore_template(app, client, login, users):
    login(users['developer'])
    with app.app_context():
        tpl = OnboardingTemplate(name='L2', structure={'blocks': []}, is_library=True,
                                 created_by=users['developer'], is_archived=True)
        db.session.add(tpl)
        db.session.commit()
        tid = tpl.id

    client.post(f'/devops/trash/template/{tid}/restore')
    with app.app_context():
        tpl = OnboardingTemplate.query.get(tid)
        assert tpl.is_archived is False
        assert tpl.archived_at is None


def test_trash_purge_template_hard_deletes_and_nullifies_instance_fk(app, client, login, users):
    login(users['developer'])
    with app.app_context():
        tpl = OnboardingTemplate(name='M', structure={'blocks': []}, is_master=True,
                                 department='product', is_archived=True)
        db.session.add(tpl)
        db.session.commit()
        tid = tpl.id
        inst = OnboardingInstance(name='o', manager_id=users['manager_of_a'],
                                  mentor_id=users['mentor_a'], structure={'blocks': []},
                                  master_template_id=tid)
        db.session.add(inst)
        db.session.commit()
        iid = inst.id

    client.post(f'/devops/trash/template/{tid}/purge')
    with app.app_context():
        assert OnboardingTemplate.query.get(tid) is None, 'purge must hard-delete'
        # the instance survives, but its dangling FK is cleared
        inst = OnboardingInstance.query.get(iid)
        assert inst is not None
        assert inst.master_template_id is None


# ── users ────────────────────────────────────────────────────────────────

def test_developer_user_delete_archives(app, client, login, users):
    login(users['developer'])
    mid = users['manager_of_a']
    r = client.post(f'/dashboard/developer/user/{mid}/delete', follow_redirects=False)
    assert r.status_code in (302, 303)
    with app.app_context():
        u = User.query.get(mid)
        assert u is not None, 'user row must survive (soft delete)'
        assert u.is_archived is True
        assert u.archived_at is not None


def test_archived_user_hidden_from_managers_query(app, users):
    with app.app_context():
        mid = users['manager_of_a']
        dev = User.query.get(users['developer'])
        assert mid in {m.id for m in managers_query_for(dev).all()}
        u = User.query.get(mid)
        u.is_archived = True
        db.session.commit()
        assert mid not in {m.id for m in managers_query_for(dev).all()}


def test_archived_user_cannot_login(app, client, users):
    with app.app_context():
        u = User.query.get(users['manager_of_a'])
        u.is_archived = True
        db.session.commit()
    # fixture users are created with password 'pw'
    r = client.post('/login', data={'login': 'mgrA', 'password': 'pw'})
    assert r.status_code == 403


def test_trash_restore_and_purge_user(app, client, login, users):
    login(users['developer'])
    with app.app_context():
        u = User.query.get(users['manager_of_b'])
        u.is_archived = True
        db.session.commit()
        uid = u.id

    client.post(f'/devops/trash/user/{uid}/restore')
    with app.app_context():
        assert User.query.get(uid).is_archived is False

    with app.app_context():
        User.query.get(uid).is_archived = True
        db.session.commit()
    client.post(f'/devops/trash/user/{uid}/purge')
    with app.app_context():
        assert User.query.get(uid) is None, 'purge must hard-delete the user'


def test_cannot_purge_self(app, client, login, users):
    login(users['developer'])
    with app.app_context():
        u = User.query.get(users['developer'])
        u.is_archived = True  # even if somehow archived, self-purge is refused
        db.session.commit()
    client.post(f"/devops/trash/user/{users['developer']}/purge")
    with app.app_context():
        assert User.query.get(users['developer']) is not None
