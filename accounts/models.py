from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models


class ClinicUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', ClinicUser.Role.ADMIN)
        return super().create_superuser(username, email=email, password=password, **extra_fields)


class ClinicUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        EMPLOYEE = 'employee', 'Employee'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    phone_number = models.CharField(max_length=20, blank=True)

    objects = ClinicUserManager()

    def clean(self):
        super().clean()
        configured_username = settings.CLINIC_ADMIN['username']
        if self.role == self.Role.ADMIN and self.username != configured_username:
            raise ValidationError('Only the configured system admin can have admin role.')

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    @property
    def is_admin_user(self):
        return self.role == self.Role.ADMIN
