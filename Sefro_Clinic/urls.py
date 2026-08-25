from django.conf import settings
from django.urls import include, path
from django.utils import translation
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework import permissions
from rest_framework.renderers import JSONRenderer


class DocsAccessPermission(permissions.BasePermission):
    """Allow anonymous access to the API docs only when explicitly enabled."""

    def has_permission(self, request, view):
        if getattr(settings, 'DOCS_PUBLIC', False):
            return True
        return bool(request.user and request.user.is_authenticated)


class SwaggerUIView(SpectacularSwaggerView):
    permission_classes = [DocsAccessPermission]


class SafeSpectacularAPIView(SpectacularAPIView):
    permission_classes = [DocsAccessPermission]
    renderer_classes = [JSONRenderer]

    def dispatch(self, request, *args, **kwargs):
        with translation.override('en-us'):
            return super().dispatch(request, *args, **kwargs)


urlpatterns = [
    path('api/schema/', SafeSpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SwaggerUIView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('customers.urls')),
    path('api/', include('logs.urls')),
]
