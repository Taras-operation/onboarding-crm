"""Per-manager block editor (#4): passed blocks are locked, you can add custom blocks that
the manager actually sees, and a passed block can't be altered."""
import json

from onboarding_crm.extensions import db
from onboarding_crm.models import OnboardingInstance
from onboarding_crm.services.master import resolve_manager_blocks


def _blocks(ids):
    return [{'type': 'stage', 'id': i, 'title': f'B{i}', 'description': '',
             'subblocks': [], 'test': {'questions': []}, 'open_questions': []} for i in ids]


def _mk_instance(app, manager_id, mentor_id, ids, completed_id=None):
    with app.app_context():
        inst = OnboardingInstance(
            name='o', manager_id=manager_id, mentor_id=mentor_id,
            structure={'blocks': _blocks(ids)}, selected_block_ids=list(ids),
            test_progress=({completed_id: {'completed': True}} if completed_id else {}),
            onboarding_step=(1 if completed_id else 0))
        db.session.add(inst)
        db.session.commit()
        return inst.id


def test_edit_adds_custom_block_manager_sees_it(app, client, login, users):
    tl, mgr = users['teamlead'], users['manager_of_a']
    iid = _mk_instance(app, mgr, tl, ['a', 'b', 'c'], completed_id='a')
    login(tl)
    assert client.get(f'/onboarding/user/edit/{mgr}').status_code == 200

    new = _blocks(['a', 'b', 'c']) + _blocks(['new1'])
    r = client.post(f'/onboarding/user/edit/{mgr}', data={'structure': json.dumps(new)})
    assert r.status_code in (302, 303)

    with app.app_context():
        inst = OnboardingInstance.query.get(iid)
        assert inst.customized is True
        assert 'new1' in (inst.selected_block_ids or [])
        ids = [b['id'] for b in inst.structure['blocks']]
        assert ids[0] == 'a'          # locked block stays first
        assert 'new1' in ids
        # the manager actually resolves the custom block
        assert any(b.get('id') == 'new1' for b in resolve_manager_blocks(inst))


def test_edit_cannot_change_passed_block(app, client, login, users):
    tl, mgr = users['teamlead'], users['manager_of_a']
    with app.app_context():
        blocks = _blocks(['a', 'b'])
        blocks[0]['title'] = 'ORIGINAL'
        inst = OnboardingInstance(name='o', manager_id=mgr, mentor_id=tl,
                                  structure={'blocks': blocks}, selected_block_ids=['a', 'b'],
                                  test_progress={'a': {'completed': True}}, onboarding_step=1)
        db.session.add(inst)
        db.session.commit()
        iid = inst.id
    login(tl)
    tampered = _blocks(['a', 'b'])
    tampered[0]['title'] = 'HACKED'
    client.post(f'/onboarding/user/edit/{mgr}', data={'structure': json.dumps(tampered)})
    with app.app_context():
        inst = OnboardingInstance.query.get(iid)
        a = next(b for b in inst.structure['blocks'] if b['id'] == 'a')
        assert a['title'] == 'ORIGINAL'  # passed block preserved verbatim
