from functools import wraps

from flask import abort
from flask_login import login_required, current_user


def roles_required(*roles):
    """Restrict a view to the given roles.

    Accepts individual ``Role`` members / strings and/or iterables of them, so both
    ``roles_required(Role.MENTOR, Role.TEAMLEAD)`` and ``roles_required(SUPERVISOR_ROLES)``
    work. Applies ``login_required`` first, then returns 403 (not a redirect) when the
    logged-in user's role is not allowed.
    """
    allowed = set()
    for r in roles:
        if isinstance(r, (set, frozenset, list, tuple)):
            allowed.update(x.value if hasattr(x, 'value') else x for x in r)
        else:
            allowed.add(r.value if hasattr(r, 'value') else r)

    def wrapper(f):
        @wraps(f)
        @login_required
        def inner(*args, **kwargs):
            if not current_user.is_authenticated or current_user.role not in allowed:
                abort(403)
            return f(*args, **kwargs)
        return inner
    return wrapper
