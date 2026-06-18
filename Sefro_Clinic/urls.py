from django.contrib import admin
from django.urls import include, path
from django.utils import translation
from rest_framework import permissions
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from rest_framework.renderers import JSONRenderer


class PublicSwaggerView(SpectacularSwaggerView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []


class SafeSpectacularAPIView(SpectacularAPIView):
    permission_classes = [permissions.AllowAny]
    authentication_classes = []
    renderer_classes = [JSONRenderer]

    def dispatch(self, request, *args, **kwargs):
        with translation.override('en-us'):
            return super().dispatch(request, *args, **kwargs)


urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/schema/', SafeSpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', PublicSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('api/auth/', include('accounts.urls')),
    path('api/', include('customers.urls')),
    path('api/inventory/', include('inventory.urls')),
]
