"""Devops ("library head") tools: a template library + a block constructor.

Blocks are copied (with FRESH ids) so everything stays independent — departments never
see each other's edits; sending to a department is always a copy into that department's
master. (v2, later: a live block library where edits propagate — not this file.)
"""

import copy
import uuid

from onboarding_crm.extensions import db
from onboarding_crm.models import OnboardingTemplate
from onboarding_crm.services.master import normalize_blocks, ensure_block_ids, get_or_create_master


def _new_id():
    return uuid.uuid4().hex[:12]


def copy_blocks(source_structure, block_ids):
    """Deep-copy the chosen blocks (in source order), giving each a brand-new id so the
    copy is fully independent from the donor."""
    wanted = set(block_ids or [])
    out = []
    for b in normalize_blocks(source_structure):
        if isinstance(b, dict) and b.get('id') in wanted:
            nb = copy.deepcopy(b)
            nb['id'] = _new_id()
            out.append(nb)
    return out


def library_templates():
    """All library templates (devops pool)."""
    return (OnboardingTemplate.query
            .filter_by(is_library=True, is_archived=False)
            .order_by(OnboardingTemplate.id.desc())
            .all())


def pull_sources(exclude_id=None):
    """Templates a devops can pull blocks FROM — any non-archived template except the target."""
    q = OnboardingTemplate.query.filter_by(is_archived=False).order_by(OnboardingTemplate.id.desc())
    return [t for t in q.all() if t.id != exclude_id]


def add_blocks_to_template(target, source_template, block_ids):
    """Append copies (new ids) of the chosen source blocks to the target template."""
    copies = copy_blocks(source_template.structure, block_ids)
    existing = normalize_blocks(target.structure)
    target.structure = ensure_block_ids({'blocks': existing + copies})
    db.session.commit()
    return len(copies)


def send_to_department(template, department, mode='append', created_by=None):
    """Copy this template's blocks into the department's master (replace or append)."""
    all_ids = [b.get('id') for b in normalize_blocks(template.structure) if b.get('id')]
    copies = copy_blocks(template.structure, all_ids)

    master = get_or_create_master(department, created_by=created_by)
    if mode == 'replace':
        master.structure = ensure_block_ids({'blocks': copies})
    else:  # append (default)
        existing = normalize_blocks(master.structure)
        master.structure = ensure_block_ids({'blocks': existing + copies})
    db.session.commit()
    return master, len(copies)
