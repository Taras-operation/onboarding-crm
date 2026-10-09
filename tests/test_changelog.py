"""Template change log: every deliberate save of a template records who changed what,
summarised by category (blocks/subblocks/tests/open questions). Visible to developer +
admin only."""
import json

from werkzeug.security import generate_password_hash

from onboarding_crm.extensions import db
from onboarding_crm.models import User, OnboardingTemplate, TemplateChangeLog


def _mk(app, role, username):
    with app.app_context():
        u = User(username=username, password=generate_password_hash('pw'),
                 role=role, department=None, is_active=True)
        db.session.add(u)
        db.session.commit()
        return u.id


def _mk_lib(app, blocks=0):
    with app.app_context():
        t = OnboardingTemplate(
            name='Lib', is_library=True, department='',
            structure={'blocks': [{'type': 'stage', 'title': f'B{i}'} for i in range(blocks)]},
        )
        db.session.add(t)
        db.session.commit()
        return t.id


def _blocks(n, subs=0, tests=0):
    out = []
    for i in range(n):
        out.append({
            'type': 'stage', 'title': f'B{i}', 'description': '',
            'subblocks': [{'title': f's{j}', 'description': ''} for j in range(subs)],
            'test': {'questions': [{'question': f'q{k}',
                                    'answers': [{'value': 'a', 'correct': True}]}
                                   for k in range(tests)]},
            'open_questions': [],
        })
    return out


def _save(client, tid, blocks, name='Lib'):
    return client.post(f'/onboarding/template/add?template_id={tid}',
                       data={'structure': json.dumps(blocks),
                             'name': name, 'selected_manager': 'template'})


# ── logging ──────────────────────────────────────────────────────────────────

def test_edit_logs_category_deltas(app, client, login):
    login(_mk(app, 'developer', 'dev'))
    tid = _mk_lib(app, blocks=0)
    assert _save(client, tid, _blocks(3, subs=2, tests=1)).status_code in (302, 303)

    with app.app_context():
        rows = TemplateChangeLog.query.all()
        assert len(rows) == 1
        e = rows[0]
        assert e.action == 'updated'
        assert e.username == 'dev'
        assert 'блоки +3' in e.summary
        assert 'сабблоки +6' in e.summary   # 3 blocks × 2 subs
        assert 'тести +3' in e.summary      # 3 blocks × 1 test


def test_removing_items_is_logged_as_minus(app, client, login):
    login(_mk(app, 'developer', 'dev'))
    tid = _mk_lib(app, blocks=0)
    _save(client, tid, _blocks(4))
    _save(client, tid, _blocks(1))   # removed 3 blocks
    with app.app_context():
        last = TemplateChangeLog.query.order_by(TemplateChangeLog.id.desc()).first()
        assert '−' in last.summary and 'блоки' in last.summary  # "блоки −3"


def test_noop_save_is_not_logged(app, client, login):
    login(_mk(app, 'developer', 'dev'))
    tid = _mk_lib(app, blocks=0)
    _save(client, tid, _blocks(2))
    # Re-save the EXACT stored structure (ids included) → nothing changed → no new row.
    with app.app_context():
        stored = OnboardingTemplate.query.get(tid).structure['blocks']
    _save(client, tid, stored)
    with app.app_context():
        assert TemplateChangeLog.query.count() == 1


def test_archive_and_restore_are_logged(app, client, login):
    login(_mk(app, 'developer', 'dev'))
    tid = _mk_lib(app, blocks=1)
    assert client.post(f'/devops/library/{tid}/delete').status_code in (302, 303)
    assert client.post(f'/devops/trash/template/{tid}/restore').status_code in (302, 303)
    with app.app_context():
        actions = [r.action for r in TemplateChangeLog.query.order_by(TemplateChangeLog.id).all()]
        assert actions == ['archived', 'restored']


# ── who can see the journal ──────────────────────────────────────────────────

def test_changelog_visible_to_dev_and_admin(app, client, login):
    for role in ('developer', 'admin'):
        login(_mk(app, role, f'{role}_u'))
        assert client.get('/devops/changelog').status_code == 200


def test_changelog_hidden_from_non_super_roles(app, client, login):
    login(_mk(app, 'manager', 'mgr'))
    assert client.get('/devops/changelog').status_code == 403
