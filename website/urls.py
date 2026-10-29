from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    ContactMessageCreateView,
    SitePackageViewSet,
    SiteProductViewSet,
    SiteServiceViewSet,
    SiteSettingsPublicView,
    TeamMemberListView,
    TestimonialListView,
    WebsiteContactDashboardViewSet,
    WebsiteDashboardLoginAPIView,
    WebsiteDashboardLogoutAPIView,
    WebsiteDashboardMeAPIView,
    WebsitePackageDashboardViewSet,
    WebsitePackagePriceOptionDashboardViewSet,
    WebsitePriceSyncRunView,
    WebsitePriceSyncStatusView,
    WebsiteProductDashboardViewSet,
    WebsiteServiceDashboardViewSet,
    WebsiteSettingsDashboardView,
    WebsiteTeamDashboardViewSet,
    WebsiteTestimonialDashboardViewSet,
)

router = DefaultRouter()
router.register('services', SiteServiceViewSet, basename='site-service')
router.register('packages', SitePackageViewSet, basename='site-package')
router.register('products', SiteProductViewSet, basename='site-product')

urlpatterns = [
    path('', include(router.urls)),
    path('site/settings/', SiteSettingsPublicView.as_view(), name='site-settings'),
    path('team/', TeamMemberListView.as_view(), name='site-team'),
    path('testimonials/', TestimonialListView.as_view(), name='site-testimonials'),
    path('contact/', ContactMessageCreateView.as_view(), name='site-contact'),
]

dashboard_router = DefaultRouter()
dashboard_router.register('services', WebsiteServiceDashboardViewSet, basename='website-dashboard-service')
dashboard_router.register('packages', WebsitePackageDashboardViewSet, basename='website-dashboard-package')
dashboard_router.register('package-price-options', WebsitePackagePriceOptionDashboardViewSet, basename='website-dashboard-package-price-option')
dashboard_router.register('products', WebsiteProductDashboardViewSet, basename='website-dashboard-product')
dashboard_router.register('team', WebsiteTeamDashboardViewSet, basename='website-dashboard-team')
dashboard_router.register('testimonials', WebsiteTestimonialDashboardViewSet, basename='website-dashboard-testimonial')
dashboard_router.register('contact-messages', WebsiteContactDashboardViewSet, basename='website-dashboard-contact-message')

dashboard_urlpatterns = [
    path('', include(dashboard_router.urls)),
    path('login/', WebsiteDashboardLoginAPIView.as_view(), name='website-dashboard-login-api'),
    path('me/', WebsiteDashboardMeAPIView.as_view(), name='website-dashboard-me'),
    path('logout/', WebsiteDashboardLogoutAPIView.as_view(), name='website-dashboard-logout'),
    path('price-sync/status/', WebsitePriceSyncStatusView.as_view(), name='website-price-sync-status'),
    path('price-sync/run/', WebsitePriceSyncRunView.as_view(), name='website-price-sync-run'),
    path('settings/', WebsiteSettingsDashboardView.as_view(), name='website-dashboard-settings'),
]
