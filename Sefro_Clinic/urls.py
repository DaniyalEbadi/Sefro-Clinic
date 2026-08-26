from django.urls import include, path

from .docs import EnUsJSONSchemaView, SwaggerUIView

urlpatterns = [
    # Versioned documentation (each schema is scoped to its own urlconf)
    path('api/v1/schema/', EnUsJSONSchemaView.as_view(urlconf='Sefro_Clinic.api_v1'), name='v1-schema'),
    path('api/v1/docs/', SwaggerUIView.as_view(url_name='v1-schema'), name='v1-swagger-ui'),
    path('api/v2/schema/', EnUsJSONSchemaView.as_view(urlconf='Sefro_Clinic.api_v2'), name='v2-schema'),
    path('api/v2/docs/', SwaggerUIView.as_view(url_name='v2-schema'), name='v2-swagger-ui'),

    # Legacy unversioned dashboard API: keeps current frontend working
    # untouched; /api/docs documents exactly this surface.
    path('api/schema/', EnUsJSONSchemaView.as_view(urlconf='Sefro_Clinic.api_legacy'), name='schema'),
    path('api/docs/', SwaggerUIView.as_view(url_name='schema'), name='swagger-ui'),
    path('', include('Sefro_Clinic.api_legacy')),

    # Explicit version namespaces for future clients (self-prefixed urlconfs)
    path('', include('Sefro_Clinic.api_v1')),
    path('', include('Sefro_Clinic.api_v2')),
]
