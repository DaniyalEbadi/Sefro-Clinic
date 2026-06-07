from rest_framework import permissions


class AllowDocsMiddleware:
    """Allow unauthenticated access to schema and docs endpoints."""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        return response


class AllowAnyForDocs(permissions.BasePermission):
    """Allow any access to docs and schema endpoints."""
    
    def has_permission(self, request, view):
        if request.path in ['/api/docs/', '/api/schema/']:
            return True
        return False
