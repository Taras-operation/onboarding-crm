"""Single source of truth for onboarding structure/progress math.

The onboarding ``structure`` is stored inconsistently across the app: sometimes a bare
list of blocks, sometimes ``{"blocks": [...]}``, and occasionally a JSON string (or even a
double-encoded one). Every place that counted stages re-parsed it slightly differently —
``mentor_dashboard`` used ``len(structure)`` (the number of dict keys, i.e. 1), while
``User.total_steps`` correctly counted ``type == 'stage'`` blocks. This module normalizes
once so every caller agrees.
"""

import json


def _as_blocks(structure):
    """Return the list of block dicts from any accepted structure representation."""
    if structure is None:
        return []

    # Unwrap up to two layers of JSON-string encoding.
    for _ in range(2):
        if isinstance(structure, str):
            try:
                structure = json.loads(structure)
            except (ValueError, TypeError):
                return []
        else:
            break

    if isinstance(structure, dict):
        blocks = structure.get('blocks')
    else:
        blocks = structure

    if not isinstance(blocks, list):
        return []

    return [b for b in blocks if isinstance(b, dict)]


def count_stages(structure):
    """Number of ``type == 'stage'`` blocks in an onboarding structure."""
    return sum(1 for b in _as_blocks(structure) if b.get('type') == 'stage')


def calculate_progress(instance):
    """Completion percentage (0.0–100.0) for an OnboardingInstance."""
    if instance is None:
        return 0.0
    total = count_stages(getattr(instance, 'structure', None))
    if total <= 0:
        return 0.0
    completed = min(getattr(instance, 'onboarding_step', 0) or 0, total)
    return round((completed / total) * 100, 1)
