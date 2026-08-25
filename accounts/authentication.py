from django.conf import settings
from django.middleware.csrf import CsrfViewMiddleware
from rest_framework.exceptions import PermissionDenied
from rest_framework_simplejwt.authentication import JWTAuthentication

CSRF_SAFE_METHODS = ('GET', 'HEAD', 'OPTIONS', 'TRACE')


class _CsrfChecker(CsrfViewMiddleware):
    """Reuse Django's CSRF machinery but surface failures as a reason string."""

    def _reject(self, request, reason):
        return reason


class CookieJWTAuthentication(JWTAuthentication):
    def authenticate(self, request):
        header = self.get_header(request)
        if header is not None:
            return super().authenticate(request)

        raw_token = request.COOKIES.get(settings.JWT_AUTH_COOKIE)
        if raw_token is None:
            return None

        if request.method not in CSRF_SAFE_METHODS:
            self._enforce_csrf(request)

        validated_token = self.get_validated_token(raw_token)
        return self.get_user(validated_token), validated_token

    def _enforce_csrf(self, request):
        checker = _CsrfChecker(lambda req: None)
        checker.process_request(request)
        reason = checker.process_view(request, None, (), {})
        if reason:
            raise PermissionDenied('CSRF verification failed.')
