from django.contrib import admin

from .models import (
    ExchangeRate,
    Expense,
    ExpenseCategory,
    Package,
    PackageItem,
    PackageService,
    PaymentComponent,
    ProductCostHistory,
    ProductPurchase,
    ProductUsage,
    Sale,
    ServiceItem,
    Wallet,
    WalletRewardRule,
    WalletTransaction,
)


@admin.register(ExchangeRate)
class ExchangeRateAdmin(admin.ModelAdmin):
    list_display = ['currency_from', 'currency_to', 'rate', 'effective_at', 'is_active']
    list_filter = ['currency_from', 'currency_to', 'is_active']
    search_fields = ['source']


@admin.register(WalletRewardRule)
class WalletRewardRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule_type', 'value', 'min_base_amount_usd', 'is_active', 'start_date', 'end_date']
    list_filter = ['rule_type', 'is_active']


@admin.register(Wallet)
class WalletAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'currency', 'balance', 'updated_at']
    search_fields = ['customer__first_name', 'customer__last_name']


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ['id', 'wallet', 'transaction_type', 'amount', 'balance_after', 'created_at']
    list_filter = ['transaction_type']
    search_fields = ['reference_type', 'description']


@admin.register(Package)
class PackageAdmin(admin.ModelAdmin):
    list_display = ['id', 'name', 'price_usd', 'is_active', 'created_at']
    search_fields = ['name']
    filter_horizontal = ['package_services', 'items']


@admin.register(ServiceItem)
class ServiceItemAdmin(admin.ModelAdmin):
    list_display = ['service', 'product', 'quantity']


@admin.register(PackageItem)
class PackageItemAdmin(admin.ModelAdmin):
    list_display = ['package', 'product', 'quantity']


@admin.register(PackageService)
class PackageServiceAdmin(admin.ModelAdmin):
    list_display = ['package', 'service']


@admin.register(ProductCostHistory)
class ProductCostHistoryAdmin(admin.ModelAdmin):
    list_display = ['product', 'cost_usd', 'effective_from', 'effective_to']
    list_filter = ['product']


@admin.register(ProductUsage)
class ProductUsageAdmin(admin.ModelAdmin):
    list_display = ['product', 'visit', 'service', 'package_sale', 'quantity', 'total_cost_usd_snapshot', 'created_at']
    list_filter = ['product']


@admin.register(Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ['id', 'customer', 'visit', 'package', 'amount_usd', 'status', 'created_at']
    list_filter = ['status']


@admin.register(PaymentComponent)
class PaymentComponentAdmin(admin.ModelAdmin):
    list_display = ['sale', 'method', 'amount_usd', 'created_at']


@admin.register(ExpenseCategory)
class ExpenseCategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'is_active']


@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display = ['id', 'created_by', 'category', 'amount_usd', 'status', 'expense_date']
    list_filter = ['status', 'category']


@admin.register(ProductPurchase)
class ProductPurchaseAdmin(admin.ModelAdmin):
    list_display = ['product', 'quantity', 'unit_cost_usd', 'total_cost_usd', 'purchase_date']
    list_filter = ['product']
