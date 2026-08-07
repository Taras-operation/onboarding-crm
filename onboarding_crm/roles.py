from enum import Enum


class Role(str, Enum):
    """Canonical set of user roles.

    Subclasses ``str`` so a ``Role`` compares equal to (and hashes like) its plain
    string value — ``Role.MENTOR == 'mentor'`` and ``Role.MENTOR in {'mentor'}`` are
    both True. That lets these enum members drop into existing string comparisons and
    SQLAlchemy filters without breaking anything during the migration away from literals.
    """

    DEVELOPER = 'developer'
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
