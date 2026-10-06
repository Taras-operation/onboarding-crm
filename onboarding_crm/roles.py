from enum import Enum


class Role(str, Enum):
    """Canonical set of user roles.

    Subclasses ``str`` so a ``Role`` compares equal to (and hashes like) its plain
    string value — ``Role.MENTOR == 'mentor'`` and ``Role.MENTOR in {'mentor'}`` are
    both True. That lets these enum members drop into existing string comparisons and
    SQLAlchemy filters without breaking anything during the migration away from literals.
    """

    DEVELOPER = 'developer'
    ADMIN = 'admin'
    TEAMLEAD = 'teamlead'
    HEAD = 'head'
    MENTOR = 'mentor'
    MANAGER = 'manager'

    @classmethod
    def values(cls):
        return [r.value for r in cls]

    def __str__(self):  # so f"{Role.MENTOR}" renders "mentor", not "Role.MENTOR"
        return self.value


# Roles that manage other people's onboarding (everyone except a plain manager).
SUPERVISOR_ROLES = {Role.MENTOR, Role.TEAMLEAD, Role.HEAD, Role.DEVELOPER}

# Super-admin cabinet (devops: template library, constructor, send-to-department,
# onboardings overview, Кошик restore/soft-delete). ADMIN is a "template steward": it
# shares the devops TEMPLATE workflow but NOT the destructive/account powers that stay
# developer-only (hard purge from the trash, user management, creating privileged roles).
SUPER_ROLES = {Role.DEVELOPER, Role.ADMIN}
