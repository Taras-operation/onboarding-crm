"""Final-decision banner gating (#5) and the 'new progress' flag for reviewers (#4)."""
from werkzeug.security import generate_password_hash

from onboarding_crm.extensions import db
from onboarding_crm.models import User, OnboardingInstance


def _mk(app, role, username, dept='product'):
    with app.app_context():
        u = User(username=username, password=generate_password_hash('pw'),
                 role=role, department=dept, is_active=True)
        db.session.add(u)
        db.session.commit()
        return u.id


def _mk_instance(app, manager_id, mentor_id, n_blocks, completed, reviewed=0):
    blocks = [{'type': 'stage', 'id': f'b{i}', 'title': f'B{i}'} for i in range(n_blocks)]
    progress = {f'b{i}': {'completed': True} for i in range(completed)}
    with app.app_context():
        inst = OnboardingInstance(
            name='o', manager_id=manager_id, mentor_id=mentor_id,
            structure={'blocks': blocks}, selected_block_ids=[b['id'] for b in blocks],
            test_progress=progress, reviewed_blocks=reviewed, onboarding_step=completed)
        db.session.add(inst)
        db.session.commit()
        return inst.id


# ── #5: the "final decision" banner only after every block is done ────────────

def test_final_banner_hidden_when_partial(app, client, login):
    dev = _mk(app, 'developer', 'dev', dept=None)
    mgr = _mk(app, 'manager', 'm1')
    iid = _mk_instance(app, mgr, dev, n_blocks=15, completed=2)  # 2/15
    login(dev)
    html = client.get(f'/manager_results/{mgr}/{iid}').get_data(as_text=True)
    assert 'До фінального фідбеку' not in html


def test_final_banner_shown_when_all_done(app, client, login):
    dev = _mk(app, 'developer', 'dev', dept=None)
    mgr = _mk(app, 'manager', 'm1')
    iid = _mk_instance(app, mgr, dev, n_blocks=3, completed=3)  # all done, no open qs
    login(dev)
    html = client.get(f'/manager_results/{mgr}/{iid}').get_data(as_text=True)
    assert 'До фінального фідбеку' in html


# ── #4: new-progress flag in plans, cleared when results are opened ───────────

def test_plans_flags_new_progress(app, client, login):
    dev = _mk(app, 'developer', 'dev', dept=None)
    mgr = _mk(app, 'manager', 'm1')
    _mk_instance(app, mgr, dev, n_blocks=5, completed=3, reviewed=1)  # 2 new
    login(dev)
    html = client.get('/onboarding/plans').get_data(as_text=True)
    assert ' нов.' in html   # row badge "🔔 N нов." (not the always-present topbar bell)


def test_opening_results_marks_progress_seen(app, client, login):
    dev = _mk(app, 'developer', 'dev', dept=None)
    mgr = _mk(app, 'manager', 'm1')
    iid = _mk_instance(app, mgr, dev, n_blocks=5, completed=3, reviewed=0)
    login(dev)
    client.get(f'/manager_results/{mgr}/{iid}')
    with app.app_context():
        assert OnboardingInstance.query.get(iid).reviewed_blocks == 3
    # plans no longer flags it as new (row badge gone; the topbar bell may still render)
    assert ' нов.' not in client.get('/onboarding/plans').get_data(as_text=True)
