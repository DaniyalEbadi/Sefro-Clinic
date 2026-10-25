"""Rate limits isolated from clinic/financial API users and anonymous traffic."""

from rest_framework.throttling import SimpleRateThrottle


class WebsitePublicReadThrottle(SimpleRateThrottle):
    scope = 'website_public'

    def get_cache_key(self, request, view):
        return self.cache_format % {'scope': self.scope, 'ident': self.get_ident(request)}


class WebsiteDashboardThrottle(SimpleRateThrottle):
    scope = 'website_dashboard'

    def get_cache_key(self, request, view):
        credential_id = getattr(request.auth, 'credential_id', None)
        if credential_id is None:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': credential_id}
