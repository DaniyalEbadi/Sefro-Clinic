from django.contrib import admin

from .models import Customer, Payment, Service, Visit


@admin.register(Service)
class ServiceAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_active')
    list_filter = ('is_active',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('first_name', 'last_name', 'mobile_number', 'bitmoji_code')
    search_fields = ('first_name', 'last_name', 'mobile_number', 'national_id', 'bitmoji_code')


@admin.register(Visit)
class VisitAdmin(admin.ModelAdmin):
    list_display = ('customer', 'start_at', 'end_at', 'status', 'staff')
    list_filter = ('status', 'start_at')
    filter_horizontal = ('services',)


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'amount', 'payment_method', 'paid_at')
    list_filter = ('payment_method', 'paid_at')
