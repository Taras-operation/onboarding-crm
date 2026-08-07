"""Object-ownership checks (IDOR protection).

``roles_required`` closes *which role* may hit a route; these helpers close *which
objects* that user may touch. A mentor and another mentor share the ``mentor`` role but
must not reach each other's managers, so role alone is never enough on routes that take
an ``<int:id>``.

This module imports only models + roles (never routes.py) to stay free of import cycles;
routes.py delegates its ``_allowed_managers_for_current_user`` / ``_visible_templates_...``
helpers here so there is a single source of truth.
"""

from flask import abort
from flask_login import current_user

from onboarding_crm.models import User, OnboardingTemplate
from onboarding_crm.roles import Role


def managers_query_for(user):
    """SQLAlchemy query for the manager users ``user`` is allowed to see/select.

    - mentor    -> managers they created, in their department
    - teamlead  -> managers created by their mentors (or themselves), in their department
    - head      -> all managers in their department
    - developer -> all managers
    - otherwise -> empty query
    """
    if not getattr(user, 'is_authenticated', False):
        return User.query.filter(False)

    role = user.role

    if role == Role.DEVELOPER:
        return User.query.filter_by(role=Role.MANAGER.value)

    if role == Role.MENTOR:
        return User.query.filter_by(
            role=Role.MANAGER.value,
            added_by_id=user.id,
            department=user.department,
        )

    if role == Role.TEAMLEAD:
        mentors = User.query.filter_by(
            role=Role.MENTOR.value,
            added_by_id=user.id,
            department=user.department,
        ).all()
        mentor_ids = [m.id for m in mentors] + [user.id]
        return User.query.filter(
            User.role == Role.MANAGER.value,
            User.added_by_id.in_(mentor_ids),
            User.department == user.department,
        )

    if role == Role.HEAD:
        return User.query.filter_by(
            role=Role.MANAGER.value,
            department=user.department,
        )

    return User.query.filter(False)


def allowed_manager_ids(user=None):
    user = user or current_user
    return {m.id for m in managers_query_for(user).all()}


def visible_templates_for(user=None):
    """Templates visible to ``user``: developer sees all; otherwise own-department,
    own-created, global, or explicitly shared to the user's department."""
    user = user or current_user
    templates = OnboardingTemplate.query.order_by(OnboardingTemplate.id.desc()).all()

    if not getattr(user, 'is_authenticated', False):
        return []

    if user.role == Role.DEVELOPER:
        return templates

    visible = []
    user_department = (user.department or '').strip()

    for template in templates:
        template_department = (getattr(template, 'department', None) or '').strip()
        shared_departments = getattr(template, 'shared_departments', None) or []
        if not isinstance(shared_departments, list):
            shared_departments = []

        if getattr(template, 'created_by', None) == user.id:
            visible.append(template)
        elif template_department and user_department and template_department == user_department:
            visible.append(template)
        elif bool(getattr(template, 'is_global', False)):
            visible.append(template)
        elif user_department and user_department in shared_departments:
            visible.append(template)

    return visible


# ── assertions: raise 403/404 instead of returning a bool ──────────────────────

def assert_can_manage_user(user_id, user=None):
    """403 unless ``user_id`` is a manager the current user supervises."""
    user = user or current_user
    if user.role == Role.DEVELOPER:
        return
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        abort(404)
    if uid not in allowed_manager_ids(user):
        abort(403)


def assert_can_access_instance(instance, user=None):
    """403 unless the onboarding ``instance`` belongs to a supervised manager."""
    user = user or current_user
    if instance is None:
        abort(404)
    if user.role == Role.DEVELOPER:
        return
    if instance.manager_id not in allowed_manager_ids(user):
        abort(403)


def assert_can_edit_template(template, user=None):
    """403 unless ``template`` is one the user is allowed to see (reuse for duplicate)."""
    user = user or current_user
    if template is None:
        abort(404)
    if user.role == Role.DEVELOPER:
        return
    if template.id not in {t.id for t in visible_templates_for(user)}:
        abort(403)


def assert_can_delete_template(template, user=None):
    """Deletion is stricter than visibility:
    developer always; the owner; or a teamlead/head inside the template's department.
    Global templates may be deleted only by a developer.
    """
    user = user or current_user
    if template is None:
        abort(404)
    if user.role == Role.DEVELOPER:
        return
    if bool(getattr(template, 'is_global', False)):
        abort(403)
    if getattr(template, 'created_by', None) == user.id:
        return
    tdept = (getattr(template, 'department', None) or '').strip()
    udept = (getattr(user, 'department', None) or '').strip()
    if user.role in (Role.TEAMLEAD, Role.HEAD) and tdept and udept and tdept == udept:
        return
    abort(403)
