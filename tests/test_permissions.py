"""Authorization matrix — the highest-value tests. These fail on the pre-Block-2/3/4
code and pass after."""

import pytest

from onboarding_crm.permissions import managers_query_for
from onboarding_crm.models import User, OnboardingInstance


# ── Block 2: a plain manager is locked out of the four sensitive routes ──────────

def test_manager_cannot_final_decision(client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'])
    login(users['manager_of_a'])
    r = client.post('/final_decision', data={'instance_id': inst_id, 'decision': 'approved'})
    assert r.status_code == 403


def test_manager_final_decision_does_not_mutate(app, client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'])
    login(users['manager_of_a'])
    client.post('/final_decision', data={'instance_id': inst_id, 'decision': 'approved'})
    with app.app_context():
        inst = OnboardingInstance.query.get(inst_id)
        assert inst.final_decision is None
        assert inst.archived in (False, None)


def test_manager_cannot_delete_template(client, login, users, make_template):
    tpl_id = make_template(users['mentor_a'])
    login(users['manager_of_a'])
    assert client.post(f'/onboarding/template/delete/{tpl_id}').status_code == 403


def test_manager_cannot_duplicate_template(client, login, users, make_template):
    tpl_id = make_template(users['mentor_a'])
    login(users['manager_of_a'])
    assert client.post(f'/onboarding/template/{tpl_id}/duplicate').status_code == 403


def test_manager_cannot_copy_user(client, login, users):
    login(users['manager_of_a'])
    assert client.get(f"/onboarding/user/copy/{users['manager_of_a']}").status_code == 403


def test_copy_user_does_not_clone_password_and_is_unique(app, client, login, users):
    """mentor copies own manager twice: no password reuse, usernames stay unique."""
    login(users['mentor_a'])
    r1 = client.get(f"/onboarding/user/copy/{users['manager_of_a']}")
    r2 = client.get(f"/onboarding/user/copy/{users['manager_of_a']}")
    assert r1.status_code in (302, 200) and r2.status_code in (302, 200)
    with app.app_context():
        original = User.query.get(users['manager_of_a'])
        copies = User.query.filter(User.username.like('mgrA_copy%')).all()
        assert len(copies) == 2
        assert len({c.username for c in copies}) == 2          # unique usernames
        assert all(c.password != original.password for c in copies)  # no hash reuse


# ── Block 3: IDOR — mentor_a must not reach mentor_b's manager ───────────────────

@pytest.mark.parametrize('path_tmpl', [
    '/onboarding/user/edit/{mgr}',
    '/final_feedback/{mgr}',
])
def test_mentor_a_cannot_reach_mentor_b_manager_pages(client, login, users, path_tmpl):
    login(users['mentor_a'])
    r = client.get(path_tmpl.format(mgr=users['manager_of_b']))
    assert r.status_code == 403


def test_mentor_a_cannot_view_mentor_b_results(client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_b'], users['mentor_b'])
    login(users['mentor_a'])
    r = client.get(f"/manager_results/{users['manager_of_b']}/{inst_id}")
    assert r.status_code == 403


def test_mentor_a_cannot_publish_feedback_for_b(client, login, users):
    login(users['mentor_a'])
    assert client.post(f"/publish_feedback/{users['manager_of_b']}").status_code == 403


def test_mentor_a_can_reach_own_manager(client, login, users):
    login(users['mentor_a'])
    assert client.get(f"/onboarding/user/edit/{users['manager_of_a']}").status_code in (200, 302)


# ── Visibility: mentor_a's manager list excludes mentor_b's manager ─────────────

def test_managers_query_isolation(app, users):
    with app.app_context():
        mentor_a = User.query.get(users['mentor_a'])
        ids = {m.id for m in managers_query_for(mentor_a).all()}
        assert users['manager_of_a'] in ids
        assert users['manager_of_b'] not in ids


def test_managers_list_route_ok_for_mentor(client, login, users):
    login(users['mentor_a'])
    assert client.get('/managers/list').status_code == 200


def test_deactivated_manager_hidden_from_supervisor(app, users):
    with app.app_context():
        User.query.get(users['manager_of_a']).is_active = False
        from onboarding_crm.extensions import db
        db.session.commit()
        mentor_a = User.query.get(users['mentor_a'])
        ids = {m.id for m in managers_query_for(mentor_a).all()}
        assert users['manager_of_a'] not in ids


# ── Template visibility across departments ──────────────────────────────────────

def test_mentor_cannot_see_foreign_department_template(app, users, make_template):
    from onboarding_crm.permissions import visible_templates_for
    # a template owned by a foreign department, not global, not shared
    other = None
    with app.app_context():
        from onboarding_crm.models import OnboardingTemplate
        from onboarding_crm.extensions import db
        t = OnboardingTemplate(name='foreign', structure={'blocks': []},
                               created_by=users['developer'], department='finance', is_global=False)
        db.session.add(t)
        db.session.commit()
        other = t.id
        mentor_a = User.query.get(users['mentor_a'])
        vis_ids = {t.id for t in visible_templates_for(mentor_a)}
        assert other not in vis_ids


def test_global_template_visible_to_all(app, users, make_template):
    from onboarding_crm.permissions import visible_templates_for
    gid = make_template(users['developer'], dept='finance', is_global=True)
    with app.app_context():
        mentor_a = User.query.get(users['mentor_a'])
        vis_ids = {t.id for t in visible_templates_for(mentor_a)}
        assert gid in vis_ids


# ── Block 4: every role logs in and lands somewhere; deactivated cannot ─────────

@pytest.mark.parametrize('username,expected_suffix', [
    ('dev', '/dashboard/developer'),
    ('tl', '/dashboard/mentor'),
    ('head', '/dashboard/mentor'),
    ('mentorA', '/dashboard/mentor'),
    ('mgrA', '/manager_dashboard'),
])
def test_each_role_logs_in(client, users, username, expected_suffix):
    r = client.post('/login', data={'login': username, 'password': 'pw'})
    assert r.status_code == 302
    assert r.headers['Location'].endswith(expected_suffix)


def test_deactivated_user_cannot_login(app, client, users):
    with app.app_context():
        from onboarding_crm.extensions import db
        User.query.get(users['manager_of_a']).is_active = False
        db.session.commit()
    r = client.post('/login', data={'login': 'mgrA', 'password': 'pw'})
    assert r.status_code == 403
