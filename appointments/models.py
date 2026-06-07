from django.conf import settings
from django.db import models

from customers.models import Customer, Service


class Appointment(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        COMPLETED = 'completed', 'Completed'
        CANCELED = 'canceled', 'Canceled'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='appointments')
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='appointments',
        null=True,
        blank=True,
    )
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='appointments')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['start_at']

    def __str__(self):
        return f'{self.customer} - {self.service} - {self.start_at:%Y-%m-%d %H:%M}'
