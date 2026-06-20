from threading import local

_user_local = local()


def get_current_user():
    return getattr(_user_local, 'user', None)


class RequestUserMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        _user_local.user = getattr(request, 'user', None)
        response = self.get_response(request)
        _user_local.user = None
        return response
