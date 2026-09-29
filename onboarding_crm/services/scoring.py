"""Single source of truth for onboarding completion, answer scoring and status.

Fixes the old ad-hoc math where ungraded open questions were counted as approved and
where the manager's status codes ('passed'/'rejected') never matched the stored
final_decision ('approved'/'rejected'/'needs_revision').
"""

from onboarding_crm.models import TestResult
from onboarding_crm.services.master import resolve_manager_blocks


def _pct(num, den):
    return round(num / den * 100) if den else None


def block_progress(instance):
    """How many of the manager's assigned stage blocks are completed."""
    if instance is None:
        return {'completed': 0, 'total': 0, 'finished': False}
    blocks = [b for b in resolve_manager_blocks(instance) if b.get('type') == 'stage']
    total = len(blocks)
    prog = instance.test_progress if isinstance(instance.test_progress, dict) else {}
    completed = sum(1 for b in blocks if prog.get(b.get('id'), {}).get('completed'))
    return {'completed': completed, 'total': total, 'finished': total > 0 and completed >= total}


def answer_stats(instance):
    """Correct scoring:
    - choice questions: correct / total answered;
    - open questions: approved / GRADED (ungraded ones are 'pending', not counted as pass);
    - overall: (correct + approved) / (choice_total + open_graded).
    """
    if instance is None:
        results = []
    else:
        results = TestResult.query.filter_by(onboarding_instance_id=instance.id).all()

    choice = [r for r in results if r.is_correct is not None]
    openq = [r for r in results if r.is_correct is None]

    choice_correct = sum(1 for r in choice if r.is_correct)
    choice_total = len(choice)

    open_graded = [r for r in openq if r.approved is not None]
    open_approved = sum(1 for r in openq if r.approved is True)
    open_rejected = sum(1 for r in openq if r.approved is False)
    open_total = len(openq)
    open_pending = open_total - len(open_graded)

    overall_num = choice_correct + open_approved
    overall_den = choice_total + len(open_graded)

    return {
        'choice_correct': choice_correct,
        'choice_total': choice_total,
        'choice_pct': _pct(choice_correct, choice_total),
        'open_approved': open_approved,
        'open_rejected': open_rejected,
        'open_graded': len(open_graded),
        'open_total': open_total,
        'open_pending': open_pending,
        'open_pct': _pct(open_approved, len(open_graded)),
        'overall_pct': _pct(overall_num, overall_den),
        'all_open_graded': open_total > 0 and open_pending == 0,
    }


# stored final_decision -> (label, bootstrap badge class)
_DECISION = {
    'approved': ('✅ Пройдено', 'success'),
    'rejected': ('❌ Не пройдено', 'danger'),
    'needs_revision': ('✍️ Доопрацювання', 'warning'),
}


def onboarding_status(instance):
    """A single status dict used by supervisor lists and the manager's own view."""
    if instance is None:
        return {'code': 'none', 'label': 'Не призначено', 'badge': 'secondary',
                'decided': False, 'locked': False, 'finished': False,
                'progress': {'completed': 0, 'total': 0, 'finished': False}}

    bp = block_progress(instance)
    decision = instance.final_decision
    locked = bool(instance.archived)  # approved/rejected set archived → read-only

    if decision in _DECISION:
        label, badge = _DECISION[decision]
        return {'code': decision, 'label': label, 'badge': badge,
                'decided': True, 'locked': locked, 'finished': bp['finished'], 'progress': bp}

    if bp['finished']:
        return {'code': 'awaiting', 'label': 'Завершив — очікує рішення', 'badge': 'info',
                'decided': False, 'locked': False, 'finished': True, 'progress': bp}

    if bp['completed'] > 0:
        return {'code': 'in_progress', 'label': f"Проходить ({bp['completed']}/{bp['total']})",
                'badge': 'secondary', 'decided': False, 'locked': False, 'finished': False, 'progress': bp}

    return {'code': 'not_started', 'label': 'Не розпочав', 'badge': 'light',
            'decided': False, 'locked': False, 'finished': False, 'progress': bp}
