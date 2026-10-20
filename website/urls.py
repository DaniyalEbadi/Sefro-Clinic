from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContactMessageCreateView,
    SitePackageViewSet,
    SiteProductViewSet,
    SiteServiceViewSet,
    TeamMemberListView,
    TestimonialListView,
    WebsiteDashboardLoginAPIView,
    WebsitePackageDashboardViewSet,
    WebsitePackagePriceOptionDashboardViewSet,
    WebsitePriceSyncStatusView,
    WebsiteProductDashboardViewSet,
    WebsiteServiceDashboardViewSet,
    WebsiteSettingsDashboardView,
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

dashboard_router = DefaultRouter()
dashboard_router.register('services', WebsiteServiceDashboardViewSet, basename='website-dashboard-service')
dashboard_router.register('packages', WebsitePackageDashboardViewSet, basename='website-dashboard-package')
dashboard_router.register('package-price-options', WebsitePackagePriceOptionDashboardViewSet, basename='website-dashboard-package-price-option')
dashboard_router.register('products', WebsiteProductDashboardViewSet, basename='website-dashboard-product')

dashboard_urlpatterns = [
    path('', include(dashboard_router.urls)),
    path('login/', WebsiteDashboardLoginAPIView.as_view(), name='website-dashboard-login-api'),
    path('price-sync/status/', WebsitePriceSyncStatusView.as_view(), name='website-price-sync-status'),
    path('settings/', WebsiteSettingsDashboardView.as_view(), name='website-dashboard-settings'),
]
