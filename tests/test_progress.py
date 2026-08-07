"""Pure progress math + final_decision state transitions."""

import json
import types

import pytest

from onboarding_crm.services.progress import count_stages, calculate_progress
from onboarding_crm.models import OnboardingInstance


STAGES = [{'type': 'stage'}, {'type': 'info'}, {'type': 'stage'}, {'type': 'stage'}]  # 3 stages


@pytest.mark.parametrize('structure,expected', [
    ({'blocks': STAGES}, 3),
    (STAGES, 3),
    (json.dumps({'blocks': STAGES}), 3),
    (json.dumps(json.dumps(STAGES)), 3),   # double-encoded
    (None, 0),
    ([], 0),
    ({'blocks': []}, 0),
    ('not json at all', 0),
    (12345, 0),
])
def test_count_stages(structure, expected):
    assert count_stages(structure) == expected


def _fake_instance(structure, step):
    return types.SimpleNamespace(structure=structure, onboarding_step=step)


@pytest.mark.parametrize('step,expected', [
    (0, 0.0),
    (1, round(1 / 3 * 100, 1)),
    (3, 100.0),
    (99, 100.0),   # clamped to total
])
def test_calculate_progress(step, expected):
    assert calculate_progress(_fake_instance({'blocks': STAGES}, step)) == expected


def test_calculate_progress_no_stages():
    assert calculate_progress(_fake_instance({'blocks': []}, 5)) == 0.0
    assert calculate_progress(None) == 0.0


# ── final_decision transitions (supervisor acting on own manager) ───────────────

@pytest.mark.parametrize('decision,exp_status,exp_archived', [
    ('approved', 'completed', True),
    ('rejected', 'failed', True),
])
def test_final_decision_sets_status_and_archive(app, client, login, users, make_instance,
                                                 decision, exp_status, exp_archived):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'])
    login(users['mentor_a'])
    r = client.post('/final_decision', data={'instance_id': inst_id, 'decision': decision})
    assert r.status_code in (302, 200)
    with app.app_context():
        inst = OnboardingInstance.query.get(inst_id)
        assert inst.onboarding_status == exp_status
        assert bool(inst.archived) is exp_archived


def test_final_decision_needs_revision_not_archived(app, client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'])
    login(users['mentor_a'])
    client.post('/final_decision', data={'instance_id': inst_id, 'decision': 'needs_revision'})
    with app.app_context():
        inst = OnboardingInstance.query.get(inst_id)
        assert inst.onboarding_status == 'revision'
        assert bool(inst.archived) is False


def test_final_decision_rejects_unknown_decision(app, client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'])
    login(users['mentor_a'])
    client.post('/final_decision', data={'instance_id': inst_id, 'decision': 'hax'})
    with app.app_context():
        inst = OnboardingInstance.query.get(inst_id)
        assert inst.final_decision is None  # never written


def test_final_decision_blocked_on_archived_instance(app, client, login, users, make_instance):
    inst_id = make_instance(users['manager_of_a'], users['mentor_a'], archived=True)
    login(users['mentor_a'])
    client.post('/final_decision', data={'instance_id': inst_id, 'decision': 'rejected'})
    with app.app_context():
        inst = OnboardingInstance.query.get(inst_id)
        # An already-closed onboarding is not re-decided.
        assert inst.final_decision is None
