from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CheckoutView,
    DashboardView,
    ExchangeRateViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    FinancialSummaryView,
    OperatingExpenseCategoryViewSet,
    OperatingExpenseViewSet,
    PackageItemViewSet,
    PackageServiceViewSet,
    PackageViewSet,
    ProductCostHistoryViewSet,
    ProductPurchaseViewSet,
    ProductUsageViewSet,
    ProfitByPackageView,
    ProfitByServiceView,
    ProfitByStaffView,
    RecordConsumptionView,
    SaleViewSet,
    ServiceItemViewSet,
    StaffCompensationRuleViewSet,
    StaffPayoutSummaryView,
    StaffPayoutViewSet,
    WalletRewardRuleViewSet,
    WalletSummaryView,
    WalletTransactionViewSet,
    WalletViewSet,
    WelcomePackItemViewSet,
    WelcomePackReportView,
    WelcomePackUsageViewSet,
    WelcomePackViewSet,
)

router = DefaultRouter()
router.register('exchange-rates', ExchangeRateViewSet, basename='exchange-rate')
router.register('reward-rules', WalletRewardRuleViewSet, basename='reward-rule')
router.register('packages', PackageViewSet, basename='package')
router.register('service-items', ServiceItemViewSet, basename='service-item')
router.register('package-items', PackageItemViewSet, basename='package-item')
router.register('package-services', PackageServiceViewSet, basename='package-service')
router.register('product-cost-history', ProductCostHistoryViewSet, basename='product-cost-history')
router.register('product-usages', ProductUsageViewSet, basename='product-usage')
router.register('wallets', WalletViewSet, basename='wallet')
router.register('wallet-transactions', WalletTransactionViewSet, basename='wallet-transaction')
router.register('sales', SaleViewSet, basename='sale')
router.register('expense-categories', ExpenseCategoryViewSet, basename='expense-category')
router.register('expenses', ExpenseViewSet, basename='expense')
router.register('operating-expense-categories', OperatingExpenseCategoryViewSet, basename='operating-expense-category')
router.register('operating-expenses', OperatingExpenseViewSet, basename='operating-expense')
router.register('product-purchases', ProductPurchaseViewSet, basename='product-purchase')
router.register('staff-compensation-rules', StaffCompensationRuleViewSet, basename='staff-compensation-rule')
router.register('staff-payouts', StaffPayoutViewSet, basename='staff-payout')
router.register('welcome-packs', WelcomePackViewSet, basename='welcome-pack')
router.register('welcome-pack-items', WelcomePackItemViewSet, basename='welcome-pack-item')
router.register('welcome-pack-usages', WelcomePackUsageViewSet, basename='welcome-pack-usage')

urlpatterns = [
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('visits/<int:pk>/record-consumption/', RecordConsumptionView.as_view(), name='record-consumption'),
    path('reports/financial-summary/', FinancialSummaryView.as_view(), name='financial-summary'),
    path('reports/profit-by-service/', ProfitByServiceView.as_view(), name='profit-by-service'),
    path('reports/profit-by-package/', ProfitByPackageView.as_view(), name='profit-by-package'),
    path('reports/profit-by-staff/', ProfitByStaffView.as_view(), name='profit-by-staff'),
    path('reports/wallet-summary/', WalletSummaryView.as_view(), name='wallet-summary'),
    path('reports/staff-payout-summary/', StaffPayoutSummaryView.as_view(), name='staff-payout-summary'),
    path('reports/dashboard/', DashboardView.as_view(), name='dashboard'),
    path('reports/welcome-packs/', WelcomePackReportView.as_view(), name='welcome-pack-report'),
    path('', include(router.urls)),
]
