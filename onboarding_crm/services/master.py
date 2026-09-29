"""The single per-department master onboarding, and stable block ids.

Blocks were historically identified by their position in the list. That breaks the moment
a block is added/removed/reordered — so we give every block a stable `id`. A manager's
onboarding then references a *subset* of the master's blocks by id (live), instead of
copying the whole structure.
"""

import uuid

from onboarding_crm.extensions import db
from onboarding_crm.models import OnboardingTemplate


def _new_block_id():
    return uuid.uuid4().hex[:12]


def normalize_blocks(structure):
    """Return the list of block dicts from any structure shape ({'blocks':[...]} or list)."""
    if isinstance(structure, dict):
        blocks = structure.get('blocks')
    else:
        blocks = structure
    return blocks if isinstance(blocks, list) else []


def ensure_block_ids(structure):
    """Assign a stable `id` to every block that lacks one. Mutates and returns
    the {'blocks': [...]} form."""
    blocks = normalize_blocks(structure)
    seen = set()
    for block in blocks:
        if not isinstance(block, dict):
            continue
        bid = block.get('id')
        if not bid or bid in seen:
            bid = _new_block_id()
            block['id'] = bid
        seen.add(bid)
    return {'blocks': blocks}


def get_master(department):
    """The department's master template, or None."""
    dept = (department or '').strip()
    return (OnboardingTemplate.query
            .filter_by(is_master=True, department=dept)
            .order_by(OnboardingTemplate.id.asc())
            .first())


def get_or_create_master(department, created_by=None):
    """Return the department's single master, creating an empty one if needed."""
    dept = (department or '').strip() or 'product'
    master = get_master(dept)
    if master:
        # make sure existing blocks have ids (lazy backfill)
        master.structure = ensure_block_ids(master.structure or {'blocks': []})
        db.session.commit()
        return master

    master = OnboardingTemplate(
        name=f"Майстер онбордингу — {dept}",
        structure={'blocks': []},
        department=dept,
        is_master=True,
        created_by=created_by,
    )
    db.session.add(master)
    db.session.commit()
    return master


def master_blocks(department):
    """Ordered list of the department master's blocks (each with a stable id)."""
    master = get_master(department)
    if not master:
        return []
    return normalize_blocks(master.structure)
