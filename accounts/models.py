from django.conf import settings
from django.contrib.auth.models import AbstractUser, UserManager
from django.core.exceptions import ValidationError
from django.db import models

from Sefro_Clinic.shamsi_storage import install_shamsi_mirrors
from Sefro_Clinic.validators import TEXT_SANITIZERS as NAME_SANITIZERS


class ClinicUserManager(UserManager):
    def create_superuser(self, username, email=None, password=None, **extra_fields):
        extra_fields.setdefault('role', ClinicUser.Role.ADMIN)
        return super().create_superuser(username, email=email, password=password, **extra_fields)


class ClinicUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'admin', 'Admin'
        EMPLOYEE = 'employee', 'Employee'

    class CompensationRole(models.TextChoices):
        """Which operator role this staff member performs.

        Value-identical to ``customers.Service.CompensationRole`` and
        ``finance.StaffCompensationRule.Role`` (accounts must not import
        either app, so the choices are mirrored here -- the *values* are the
        contract between the three).
        """

        NONE = 'none', 'No Commission'
        DOCTOR = 'doctor', 'Doctor (Injections)'
        FACIAL = 'facial', 'Facial Worker'
        LASER = 'laser', 'Laser Tech'

    role = models.CharField(max_length=20, choices=Role.choices, default=Role.EMPLOYEE)
    compensation_role = models.CharField(
        max_length=20,
        choices=CompensationRole.choices,
        default=CompensationRole.NONE,
        help_text=(
            'The operator role this staff member performs. Services tagged with '
            'this role resolve their visit payout to this person.'
        ),
    )
    phone_number = models.CharField(max_length=20, blank=True)
    username = models.CharField(
        max_length=150,
        unique=True,
        validators=[*AbstractUser.username.field.validators, *NAME_SANITIZERS],
    )
    first_name = models.CharField(max_length=150, blank=True, validators=NAME_SANITIZERS)
    last_name = models.CharField(max_length=150, blank=True, validators=NAME_SANITIZERS)

    objects = ClinicUserManager()

    class Meta:
        ordering = ['username']

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


install_shamsi_mirrors(globals())
