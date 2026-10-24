from rest_framework.permissions import BasePermission

from accounts.models import ClinicUser

from .models import WebsiteDashboardSession


class IsWebsiteManager(BasePermission):
    def has_permission(self, request, view):
        return (
            request.user.is_authenticated
            and isinstance(request.auth, WebsiteDashboardSession)
            and request.user.role in (ClinicUser.Role.ADMIN, ClinicUser.Role.EMPLOYEE)
        )
