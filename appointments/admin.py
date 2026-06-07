from django.contrib import admin

from .models import Appointment


@admin.register(Appointment)
class AppointmentAdmin(admin.ModelAdmin):
    list_display = ('customer', 'service', 'start_at', 'end_at', 'status')
    list_filter = ('status', 'start_at')
