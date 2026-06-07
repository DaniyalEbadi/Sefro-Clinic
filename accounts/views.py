from datetime import timedelta

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import ClinicUser
from .serializers import ClinicUserSerializer, EmployeeCreateSerializer, EmployeeUpdateSerializer


def set_jwt_cookies(response, access_token=None, refresh_token=None):
    cookie_options = {
        'httponly': settings.JWT_AUTH_COOKIE_HTTP_ONLY,
        'secure': settings.JWT_AUTH_COOKIE_SECURE,
        'samesite': settings.JWT_AUTH_COOKIE_SAMESITE,
        'path': '/',
        'max_age': int(timedelta(days=7).total_seconds()),
    }
    if access_token:
        response.set_cookie(settings.JWT_AUTH_COOKIE, access_token, **cookie_options)
    if refresh_token:
        response.set_cookie(settings.JWT_AUTH_REFRESH_COOKIE, refresh_token, **cookie_options)


def clear_jwt_cookies(response):
    response.delete_cookie(settings.JWT_AUTH_COOKIE, path='/', samesite=settings.JWT_AUTH_COOKIE_SAMESITE)
    response.delete_cookie(settings.JWT_AUTH_REFRESH_COOKIE, path='/', samesite=settings.JWT_AUTH_COOKIE_SAMESITE)


@extend_schema(tags=['Authentication'])
class ClinicTokenObtainPairView(TokenObtainPairView):
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        access_token = response.data.get('access')
        refresh_token = response.data.get('refresh')
        set_jwt_cookies(response, access_token=access_token, refresh_token=refresh_token)
        return response


@extend_schema(tags=['Authentication'])
class ClinicTokenRefreshView(TokenRefreshView):
    def post(self, request, *args, **kwargs):
        if 'refresh' not in request.data:
            refresh_token = request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
            if refresh_token:
                request.data['refresh'] = refresh_token

        response = super().post(request, *args, **kwargs)
        set_jwt_cookies(response, access_token=response.data.get('access'))
        return response


@extend_schema(tags=['Authentication'])
class LogoutAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        response = Response({'detail': 'Logged out.'})
        clear_jwt_cookies(response)
        return response


class MeAPIView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(tags=['Authentication'], responses=ClinicUserSerializer)
    def get(self, request):
        return Response(ClinicUserSerializer(request.user).data)


@extend_schema(tags=['Employees'])
class EmployeeCreateAPIView(generics.CreateAPIView):
    queryset = ClinicUser.objects.filter(role=ClinicUser.Role.EMPLOYEE)
    serializer_class = EmployeeCreateSerializer
    permission_classes = [permissions.IsAdminUser]


@extend_schema(tags=['Employees'])
class EmployeeListAPIView(generics.ListAPIView):
    queryset = ClinicUser.objects.filter(role=ClinicUser.Role.EMPLOYEE)
    serializer_class = ClinicUserSerializer
    permission_classes = [permissions.IsAdminUser]


@extend_schema(tags=['Employees'])
class EmployeeRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ClinicUser.objects.filter(role=ClinicUser.Role.EMPLOYEE)
    permission_classes = [permissions.IsAdminUser]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return EmployeeUpdateSerializer
        return ClinicUserSerializer
