from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (AllReportsView, CustomerReportView, CustomerViewSet,
                    DailyReportView, DashboardAPIView, MonthlyReportView,
                    PaymentViewSet, QuarterlyReportView, ReferralReportView,
                    ReportsAPIView, ServiceViewSet, VisitReportView,
                    VisitViewSet, WeeklyReportView, WorkTimeViewSet,
                    YearlyReportView)


router = DefaultRouter()
router.register('customers', CustomerViewSet, basename='customer')
router.register('services', ServiceViewSet, basename='service')
router.register('visits', VisitViewSet, basename='visit')
router.register('payments', PaymentViewSet, basename='payment')
router.register('work-time', WorkTimeViewSet, basename='work-time')

urlpatterns = [
    path('dashboard/', DashboardAPIView.as_view(), name='dashboard'),
    path('reports/', ReportsAPIView.as_view(), name='reports'),
    path('reports/daily/', DailyReportView.as_view(), name='report-daily'),
    path('reports/weekly/', WeeklyReportView.as_view(), name='report-weekly'),
    path('reports/monthly/', MonthlyReportView.as_view(), name='report-monthly'),
    path('reports/quarterly/', QuarterlyReportView.as_view(), name='report-quarterly'),
    path('reports/yearly/', YearlyReportView.as_view(), name='report-yearly'),
    path('reports/all/', AllReportsView.as_view(), name='report-all'),
    path('reports/visits/', VisitReportView.as_view(), name='report-visits'),
    path('reports/customers/', CustomerReportView.as_view(), name='report-customers'),
    path('reports/referral/', ReferralReportView.as_view(), name='report-referral'),
    path('', include(router.urls)),
]
