from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import CustomerViewSet, DashboardAPIView, PaymentViewSet, ServiceViewSet, VisitViewSet


router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('services', ServiceViewSet, basename='service')
router.register('visits', VisitViewSet, basename='visit')
router.register('payments', PaymentViewSet, basename='payment')

urlpatterns = [
    path('dashboard/', DashboardAPIView.as_view(), name='dashboard'),
    path('', include(router.urls)),
]
