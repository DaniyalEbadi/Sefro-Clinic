from django.urls import include, path

from .docs import EnUsJSONSchemaView, SwaggerUIView


class SiteSchemaView(EnUsJSONSchemaView):
    urlconf = 'Sefro_Clinic.api_v2'
    custom_settings = {
        'TITLE': 'Sefro Clinic Site API',
        'VERSION': '2.0.0',
        'DESCRIPTION': 'Website-facing API for barancliniccenter.com. '
                       'Independent from the financial dashboard API.',
        'TAGS': [
            {'name': 'Site Services', 'description': 'Public clinic services catalog.'},
            {'name': 'Site Packages', 'description': 'Bundled service packages with discounts.'},
            {'name': 'Site Products', 'description': 'Skincare product catalog.'},
            {'name': 'Site Team', 'description': 'Clinic specialists.'},
            {'name': 'Site Testimonials', 'description': 'Customer testimonials.'},
            {'name': 'Site Contact', 'description': 'Public contact/consultation intake.'},
        ],
    }


urlpatterns = [
    # Dashboard API (the one your current frontend consumes)
    path('api/schema/', EnUsJSONSchemaView.as_view(urlconf='Sefro_Clinic.api_legacy'), name='schema'),
    path('api/docs/', SwaggerUIView.as_view(url_name='schema'), name='swagger-ui'),
    path('', include('Sefro_Clinic.api_legacy')),

    # Site API v2
    path('api/v2/schema/', SiteSchemaView.as_view(), name='v2-schema'),
    path('api/v2/docs/', SwaggerUIView.as_view(url_name='v2-schema'), name='v2-swagger-ui'),
    path('', include('Sefro_Clinic.api_v2')),
]
