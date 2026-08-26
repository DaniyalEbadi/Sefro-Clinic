from django.urls import include, path
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView


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
        ]),
    ),
]
