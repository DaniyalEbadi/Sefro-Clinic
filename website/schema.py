from django.conf import settings
from drf_spectacular.extensions import OpenApiAuthenticationExtension


class WebsiteDashboardCookieScheme(OpenApiAuthenticationExtension):
    target_class = 'website.authentication.WebsiteDashboardAuthentication'
    name = 'WebsiteDashboardCookie'

    def get_security_definition(self, auto_schema):
        return {
            'type': 'apiKey',
            'in': 'cookie',
            'name': settings.WEBSITE_DASHBOARD_COOKIE,
            'description': 'Independent HttpOnly website-manager session cookie. Unsafe requests also require X-CSRFToken.',
        }
