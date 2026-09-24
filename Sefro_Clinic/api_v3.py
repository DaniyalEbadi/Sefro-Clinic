"""OpenAPI urlconf for the Face AI Analyzer v3 docs.

Mirrors Sefro_Clinic/api_legacy.py and Sefro_Clinic/api_v2.py: declares the
prefixed routes so /api/v3/schema/ generates correct /api/v3/... paths.
"""
from django.urls import include, path

urlpatterns = [
    path('api/v3/', include('face_analyzer.urls', namespace='face_analyzer')),
]
