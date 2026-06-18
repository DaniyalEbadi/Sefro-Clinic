from django.urls import include, path
from rest_framework.routers import DefaultRouter, SimpleRouter

from .views import (CategoryViewSet, CustomerViewSet, DashboardAPIView,
                    PaymentViewSet, ServiceViewSet, VisitViewSet)


router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('services', ServiceViewSet, basename='service')
router.register('visits', VisitViewSet, basename='visit')
router.register('payments', PaymentViewSet, basename='payment')

category_router = SimpleRouter()
category_router.register('categories', CategoryViewSet, basename='service-category')

urlpatterns = [
    path('dashboard/', DashboardAPIView.as_view(), name='dashboard'),
    path('services/', include(category_router.urls)),
    path('', include(router.urls)),
]
