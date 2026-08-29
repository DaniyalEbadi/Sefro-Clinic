from rest_framework import permissions

from accounts.permissions import IsAdmin


class IsEmployeeOrAdmin(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)


class IsFinanceAdmin(IsAdmin):
    pass
