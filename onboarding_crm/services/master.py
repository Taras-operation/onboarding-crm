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


def resolve_manager_blocks(instance):
    """Ordered blocks a manager actually sees (new live-reference model):

    - a completed block → its frozen snapshot from `locked_blocks` (so later master edits
      don't rewrite what they already did);
    - otherwise → the live block from the department master, by id;
    - fallback → the assignment-time snapshot in `instance.structure` if the master block
      is gone.

    Legacy instances (no `selected_block_ids`) fall back to their own structure.
    """
    if instance is None:
        return []

    selected = instance.selected_block_ids or []
    if not selected:
        return [b for b in normalize_blocks(instance.structure) if isinstance(b, dict)]

    locked = instance.locked_blocks if isinstance(instance.locked_blocks, dict) else {}
    master = (OnboardingTemplate.query.get(instance.master_template_id)
              if instance.master_template_id else None)
    master_list = normalize_blocks(master.structure) if master else []
    master_by_id = {b.get('id'): b for b in master_list}
    snap_by_id = {b.get('id'): b for b in normalize_blocks(instance.structure)}

    # Follow the CURRENT master order so the manager sees blocks in the same order the
    # supervisor does on the selection screen. Any selected id no longer in the master
    # (removed/locked) is appended in its stored order.
    selected_set = set(selected)
    ordered_ids = [b.get('id') for b in master_list if b.get('id') in selected_set]
    for bid in selected:
        if bid not in ordered_ids:
            ordered_ids.append(bid)

    out = []
    for bid in ordered_ids:
        if isinstance(locked.get(bid), dict):
            out.append(locked[bid])
        elif bid in master_by_id:
            out.append(master_by_id[bid])
        elif bid in snap_by_id:
            out.append(snap_by_id[bid])
    return out
