from drf_spectacular.extensions import OpenApiAuthenticationExtension
from .authentication import CookieJWTAuthentication


class CookieJWTAuthenticationExtension(OpenApiAuthenticationExtension):
    target_class = CookieJWTAuthentication
    priority = 1

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': 'access_token',
            'description': 'JWT authentication token',
        }