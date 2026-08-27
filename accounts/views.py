from django.conf import settings
from django.middleware.csrf import get_token
from drf_spectacular.utils import extend_schema
from rest_framework import generics, permissions
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import ClinicUser
from .permissions import IsAdmin, IsAdminOrReadOnly
from .serializers import ClinicUserSerializer, EmployeeCreateSerializer, EmployeeUpdateSerializer


def _cookie_options(max_age):
    return {
        'httponly': settings.JWT_AUTH_COOKIE_HTTP_ONLY,
        'secure': settings.JWT_AUTH_COOKIE_SECURE,
        'samesite': settings.JWT_AUTH_COOKIE_SAMESITE,
        'path': '/',
        'max_age': max_age,
    }


def set_jwt_cookies(response, access_token=None, refresh_token=None):
    access_max_age = int(settings.SIMPLE_JWT['ACCESS_TOKEN_LIFETIME'].total_seconds())
    refresh_max_age = int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds())
    if access_token:
        response.set_cookie(
            settings.JWT_AUTH_COOKIE, access_token, **_cookie_options(access_max_age)
        )
    if refresh_token:
        response.set_cookie(
            settings.JWT_AUTH_REFRESH_COOKIE, refresh_token, **_cookie_options(refresh_max_age)
        )


def clear_jwt_cookies(response):
    response.delete_cookie(settings.JWT_AUTH_COOKIE, path='/', samesite=settings.JWT_AUTH_COOKIE_SAMESITE)
    response.delete_cookie(settings.JWT_AUTH_REFRESH_COOKIE, path='/', samesite=settings.JWT_AUTH_COOKIE_SAMESITE)



def _strip_body_tokens(response):
    if not getattr(settings, 'RETURN_TOKENS_IN_BODY', True):
        response.data.pop('access', None)
        response.data.pop('refresh', None)
    return response


@extend_schema(tags=['Authentication'])
class ClinicTokenObtainPairView(TokenObtainPairView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # Issue the CSRF cookie so cookie-authenticated clients can send X-CSRFToken.
        get_token(request)
        access = response.data.get('access')
        refresh = response.data.get('refresh')
        _strip_body_tokens(response)
        set_jwt_cookies(response, access_token=access, refresh_token=refresh)
        return response


@extend_schema(tags=['Authentication'])
class ClinicTokenRefreshView(TokenRefreshView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth'

    def post(self, request, *args, **kwargs):
        if 'refresh' not in request.data:
            refresh_token = request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
            if refresh_token:
                request.data['refresh'] = refresh_token

        response = super().post(request, *args, **kwargs)
        # With ROTATE_REFRESH_TOKENS the response carries a fresh refresh token too.
        access = response.data.get('access')
        refresh = response.data.get('refresh')
        _strip_body_tokens(response)
        set_jwt_cookies(response, access_token=access, refresh_token=refresh)
        return response


@extend_schema(tags=['Authentication'])
class LogoutAPIView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        raw_refresh = (
            request.COOKIES.get(settings.JWT_AUTH_REFRESH_COOKIE)
            or request.data.get('refresh')
        )
        if raw_refresh:
            try:
                RefreshToken(raw_refresh).blacklist()
            except TokenError:
                pass
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
    permission_classes = [permissions.IsAuthenticated, IsAdmin]


@extend_schema(tags=['Employees'])
class EmployeeListAPIView(generics.ListAPIView):
    queryset = ClinicUser.objects.filter(role=ClinicUser.Role.EMPLOYEE)
    serializer_class = ClinicUserSerializer
    permission_classes = [permissions.IsAuthenticated, IsAdmin]


@extend_schema(tags=['Employees'])
class EmployeeRetrieveUpdateDestroyAPIView(generics.RetrieveUpdateDestroyAPIView):
    queryset = ClinicUser.objects.filter(role=ClinicUser.Role.EMPLOYEE)
    permission_classes = [permissions.IsAuthenticated, IsAdminOrReadOnly]

    def get_serializer_class(self):
        if self.request.method in ('PUT', 'PATCH'):
            return EmployeeUpdateSerializer
        return ClinicUserSerializer
