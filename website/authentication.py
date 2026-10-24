"""Cookie authentication isolated from the clinic JWT session."""

import hashlib
import secrets
from datetime import timedelta

from django.conf import settings
from django.middleware.csrf import get_token
from django.utils import timezone
from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed, PermissionDenied

from accounts.authentication import CSRF_SAFE_METHODS, _CsrfChecker

from .models import WebsiteDashboardSession


def issue_website_session(response, request, credential):
    secret = secrets.token_urlsafe(48)
    lifetime = timedelta(seconds=settings.WEBSITE_DASHBOARD_SESSION_SECONDS)
    WebsiteDashboardSession.objects.create(
        credential=credential,
        token_hash=hashlib.sha256(secret.encode()).hexdigest(),
        expires_at=timezone.now() + lifetime,
    )
    get_token(request)
    response.set_cookie(
        settings.WEBSITE_DASHBOARD_COOKIE,
        secret,
        max_age=int(lifetime.total_seconds()),
        httponly=True,
        secure=settings.JWT_AUTH_COOKIE_SECURE,
        samesite=settings.JWT_AUTH_COOKIE_SAMESITE,
        path='/api/v2/site-dashboard/',
    )


def clear_website_session_cookie(response):
    response.delete_cookie(
        settings.WEBSITE_DASHBOARD_COOKIE,
        path='/api/v2/site-dashboard/',
        samesite=settings.JWT_AUTH_COOKIE_SAMESITE,
    )


def session_from_request(request):
    secret = request.COOKIES.get(settings.WEBSITE_DASHBOARD_COOKIE)
    if not secret:
        return None
    digest = hashlib.sha256(secret.encode()).hexdigest()
    return WebsiteDashboardSession.objects.select_related('credential__user').filter(token_hash=digest).first()


class WebsiteDashboardAuthentication(BaseAuthentication):
    def authenticate(self, request):
        if settings.WEBSITE_DASHBOARD_COOKIE not in request.COOKIES:
            return None
        session = session_from_request(request)
        if session is None or session.revoked_at or session.expires_at <= timezone.now():
            raise AuthenticationFailed('Website dashboard session is invalid or expired.')
        credential = session.credential
        if not credential.is_active or not credential.user.is_active:
            raise AuthenticationFailed('Website dashboard account is inactive.')
        if request.method not in CSRF_SAFE_METHODS:
            checker = _CsrfChecker(lambda req: None)
            checker.process_request(request)
            reason = checker.process_view(request, None, (), {})
            if reason:
                raise PermissionDenied('CSRF verification failed.')
        return credential.user, session

    def authenticate_header(self, request):
        return 'WebsiteSession'
