from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CheckoutView,
    ExchangeRateViewSet,
    ExpenseCategoryViewSet,
    ExpenseViewSet,
    FinancialSummaryView,
    PackageItemViewSet,
    PackageServiceViewSet,
    PackageViewSet,
    ProductCostHistoryViewSet,
    ProductPurchaseViewSet,
    ProductUsageViewSet,
    ProfitByPackageView,
    ProfitByServiceView,
    RecordConsumptionView,
    SaleViewSet,
    ServiceItemViewSet,
    WalletRewardRuleViewSet,
    WalletSummaryView,
    WalletTransactionViewSet,
    WalletViewSet,
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
router.register('product-purchases', ProductPurchaseViewSet, basename='product-purchase')

urlpatterns = [
    path('checkout/', CheckoutView.as_view(), name='checkout'),
    path('visits/<int:pk>/record-consumption/', RecordConsumptionView.as_view(), name='record-consumption'),
    path('reports/financial-summary/', FinancialSummaryView.as_view(), name='financial-summary'),
    path('reports/profit-by-service/', ProfitByServiceView.as_view(), name='profit-by-service'),
    path('reports/profit-by-package/', ProfitByPackageView.as_view(), name='profit-by-package'),
    path('reports/wallet-summary/', WalletSummaryView.as_view(), name='wallet-summary'),
    path('', include(router.urls)),
]
