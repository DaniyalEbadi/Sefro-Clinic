from django.contrib import admin

from .models import Product


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ('name', 'sku', 'unit_price', 'count', 'status', 'unit')
    search_fields = ('name', 'sku')
    list_filter = ('status',)
