from threading import local

from django.utils.deprecation import MiddlewareMixin

from accounts.authentication import CookieJWTAuthentication

_user_local = local()


def get_current_user():
    return getattr(_user_local, 'user', None)


class RequestUserMiddleware(MiddlewareMixin):
    def __call__(self, request):
        user = getattr(request, 'user', None)
        if user is None or not user.is_authenticated:
            user = self._authenticate_api(request)
        _user_local.user = user
        response = self.get_response(request)
        _user_local.user = None
        return response

    @staticmethod
    def _authenticate_api(request):
        try:
            result = CookieJWTAuthentication().authenticate(request)
        except Exception:
            return None
        if result is None:
            return None
        return result[0]
