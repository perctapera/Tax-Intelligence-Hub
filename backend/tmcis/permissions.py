from rest_framework.permissions import BasePermission


class HasTmcisRole(BasePermission):
    allowed_roles = ()

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.role in self.allowed_roles
        )


class StaffRoles:
    ADMIN = "admin"
    SUPERVISOR = "supervisor"
    OFFICER = "officer"
    MERCHANT = "merchant"

    ALL_STAFF = (ADMIN, SUPERVISOR, OFFICER)
    ADMIN_SUPERVISOR = (ADMIN, SUPERVISOR)
