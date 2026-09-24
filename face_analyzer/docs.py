"""Face AI Analyzer v3 schema + Swagger UI views.

Mirrors the Sefro_Clinic/docs.py pattern: DocsAccessPermission-gated
drf-spectacular views scoped to the v3 URLconf only.
"""

from Sefro_Clinic.docs import EnUsJSONSchemaView, SwaggerUIView


class FaceAnalyzerSchemaView(EnUsJSONSchemaView):
    urlconf = 'Sefro_Clinic.api_v3'
    custom_settings = {
        'TITLE': 'Sefro Clinic Face AI Analyzer API',
        'VERSION': '3.0.0',
        'DESCRIPTION': 'Face AI Analyzer: upload a face image and receive aesthetic '
                       'scores, detected facial attributes, personalized beauty '
                       'suggestions and a regenerable skin-care plan. Staff can '
                       'browse their own analysis history.',
        'TAGS': [
            {'name': 'Face Analyzer',
             'description': 'Public face analysis, skin-care tips and staff analysis history.'},
        ],
    }


class FaceAnalyzerSwaggerView(SwaggerUIView):
    """Swagger UI for the Face Analyzer v3 schema (url_name='v3-schema')."""
