from django.urls import include, path
from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from face_analyzer.views import (
    FaceAnalysisDetailView,
    FaceAnalysisHistoryView,
    FaceAnalysisTipsView,
    FaceAnalyzeView,
)
from website.urls import dashboard_urlpatterns
from website.urls import urlpatterns as website_patterns


@extend_schema_view(post=extend_schema(tags=['Site Face Analyzer']))
class SiteFaceAnalyzeView(FaceAnalyzeView):
    pass


@extend_schema_view(post=extend_schema(tags=['Site Face Analyzer']))
class SiteFaceAnalysisTipsView(FaceAnalysisTipsView):
    pass


@extend_schema_view(get=extend_schema(tags=['Site Face Analyzer']))
class SiteFaceAnalysisHistoryView(FaceAnalysisHistoryView):
    pass


@extend_schema_view(get=extend_schema(tags=['Site Face Analyzer']))
class SiteFaceAnalysisDetailView(FaceAnalysisDetailView):
    pass


class SiteInfoAPIView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(
        tags=['Site'],
        responses={
            200: {
                'type': 'object',
                'properties': {
                    'name': {'type': 'string', 'example': 'Sefro Clinic Site API'},
                    'version': {'type': 'string', 'example': 'v2'},
                },
            },
        },
    )
    def get(self, request):
        return Response({'name': 'Sefro Clinic Site API', 'version': 'v2'})


urlpatterns = [
    path(
        'api/v2/',
        include([
            path('site/info/', SiteInfoAPIView.as_view(), name='site-info'),
            path('face/analyze/', SiteFaceAnalyzeView.as_view(), name='site-face-analyze'),
            path('face/<int:pk>/tips/', SiteFaceAnalysisTipsView.as_view(), name='site-face-tips'),
            path('face/history/', SiteFaceAnalysisHistoryView.as_view(), name='site-face-history'),
            path('face/history/<int:pk>/', SiteFaceAnalysisDetailView.as_view(), name='site-face-history-detail'),
            path('site-dashboard/', include(dashboard_urlpatterns)),
            path('', include(website_patterns)),
        ]),
    ),
]
