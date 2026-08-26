from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContactMessageCreateView,
    SitePackageViewSet,
    SiteProductViewSet,
    SiteServiceViewSet,
    TeamMemberListView,
    TestimonialListView,
)

router = DefaultRouter()
router.register('services', SiteServiceViewSet, basename='site-service')
router.register('packages', SitePackageViewSet, basename='site-package')
router.register('products', SiteProductViewSet, basename='site-product')

urlpatterns = [
    path('', include(router.urls)),
    path('team/', TeamMemberListView.as_view(), name='site-team'),
    path('testimonials/', TestimonialListView.as_view(), name='site-testimonials'),
    path('contact/', ContactMessageCreateView.as_view(), name='site-contact'),
]
