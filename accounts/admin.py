from django.contrib import admin
from django.contrib.auth.admin import UserAdmin

from .models import ClinicUser


@admin.register(ClinicUser)
class ClinicUserAdmin(UserAdmin):
    list_display = ('username', 'first_name', 'last_name', 'role', 'is_active')
    list_filter = ('role', 'is_active')
    fieldsets = UserAdmin.fieldsets + (
        ('Clinic', {'fields': ('role', 'phone_number')}),
    )
