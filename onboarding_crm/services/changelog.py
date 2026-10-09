"""Template change log — category-level audit of who edited a template.

We don't diff content word-by-word; we count items per category (blocks, subblocks,
tests, open questions) before and after a save and record the delta, e.g.
"блоки +1, тести +2, сабблоки −1". Enough to see what each editor changed without
storing full snapshots.
"""
from flask_login import current_user

from onboarding_crm.extensions import db
from onboarding_crm.models import TemplateChangeLog

# order + ukrainian labels for the summary line
_CAT_LABELS = [
    ('blocks', 'блоки'),
    ('subblocks', 'сабблоки'),
    ('tests', 'тести'),
    ('open', 'відкриті питання'),
]
_MINUS = '−'  # real minus sign, not a hyphen


def structure_counts(blocks):
    """Count content by category in a list of stage blocks."""
    counts = {'blocks': 0, 'subblocks': 0, 'tests': 0, 'open': 0}
    for b in (blocks or []):
        if not isinstance(b, dict):
            continue
        counts['blocks'] += 1
        counts['subblocks'] += len(b.get('subblocks') or [])
        counts['tests'] += len((b.get('test') or {}).get('questions') or [])
        counts['open'] += len(b.get('open_questions') or [])
    return counts


def delta_summary(before, after):
    """'блоки +1, тести +2' — only categories that actually changed."""
    before = before or {}
    after = after or {}
    parts = []
    for key, label in _CAT_LABELS:
        d = (after.get(key) or 0) - (before.get(key) or 0)
        if d > 0:
            parts.append(f"{label} +{d}")
        elif d < 0:
            parts.append(f"{label} {_MINUS}{abs(d)}")
    return ', '.join(parts)


def _kind_of(tpl):
    if getattr(tpl, 'is_library', False):
        return 'library'
    if getattr(tpl, 'is_master', False):
        return 'master'
    return 'department'


def log_template_event(tpl, action, before=None, after=None, note=None):
    """Write one audit row. Never let a logging failure break the actual save."""
    try:
        if note is not None:
            summary = note
        elif before is not None and after is not None:
            summary = delta_summary(before, after) or 'без зміни структури'
        else:
            summary = ''

        details = None
        if before is not None or after is not None:
            details = {'before': before, 'after': after}

        db.session.add(TemplateChangeLog(
            user_id=getattr(current_user, 'id', None),
            username=getattr(current_user, 'username', None),
            user_role=getattr(current_user, 'role', None),
            template_id=getattr(tpl, 'id', None),
            template_name=getattr(tpl, 'name', None),
            action=action,
            kind=_kind_of(tpl),
            details=details,
            summary=summary,
        ))
        db.session.commit()
    except Exception as e:  # pragma: no cover — audit must never break the request
        db.session.rollback()
        print("⚠️ changelog error:", e)
