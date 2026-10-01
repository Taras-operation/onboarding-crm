"""Devops library templates are department-less raw material. Regression: the
``department`` column defaults to 'product' on None, so a new library template must be
created with '' (shows as «—») — never silently pinned to the product department."""

from onboarding_crm.extensions import db
from onboarding_crm.models import OnboardingTemplate


def test_new_library_template_has_no_department(app, client, login, users):
    login(users['developer'])
    r = client.post('/devops/library/new', data={'name': 'Довідник'}, follow_redirects=False)
    assert r.status_code in (302, 303)

    with app.app_context():
        tpl = OnboardingTemplate.query.filter_by(name='Довідник').first()
        assert tpl is not None
        assert tpl.is_library is True
        # the whole point: NOT auto-pinned to 'product'
        assert not tpl.department, f'library template must be department-less, got {tpl.department!r}'
        assert (tpl.department or '—') == '—'


def test_departmentless_library_can_be_sent_to_any_department(app, client, login, users):
    """A library template with no department isn't blocked from any department
    (the own-department guard only fires for a real department)."""
    login(users['developer'])
    client.post('/devops/library/new', data={'name': 'Універсальний'})
    with app.app_context():
        tid = OnboardingTemplate.query.filter_by(name='Універсальний').first().id
        # give it a block so there is something to send
        tpl = OnboardingTemplate.query.get(tid)
        tpl.structure = {'blocks': [{'id': 'b1', 'title': 'X'}]}
        db.session.commit()

    r = client.post(f'/devops/library/{tid}/send-to-department',
                    data={'department': 'product', 'mode': 'append'}, follow_redirects=True)
    assert r.status_code == 200
    with app.app_context():
        master = OnboardingTemplate.query.filter_by(is_master=True, department='product').first()
        assert master is not None
        assert any(b.get('title') == 'X' for b in (master.structure or {}).get('blocks', []))
