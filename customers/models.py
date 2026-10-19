from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models

from Sefro_Clinic.validators import TEXT_SANITIZERS


class ServiceCategory(models.Model):
    name = models.CharField(max_length=80, unique=True, validators=TEXT_SANITIZERS)
    slug = models.SlugField(max_length=80, unique=True)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        indexes = [
            models.Index(fields=['sort_order', 'name'], name='svc_cat_sort_idx'),
        ]

    def __str__(self):
        return self.name


class Service(models.Model):
    class CompensationRole(models.TextChoices):
        NONE = 'none', 'No Commission'
        DOCTOR = 'doctor', 'Doctor (Injections)'
        FACIAL = 'facial', 'Facial Worker'
        LASER = 'laser', 'Laser Tech'

    name = models.CharField(max_length=100, unique=True, validators=TEXT_SANITIZERS)
    description = models.TextField(blank=True, validators=TEXT_SANITIZERS)
    price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'))
    price_usd = models.DecimalField(
        max_digits=14, decimal_places=2,
        validators=[MinValueValidator(Decimal('0'))], default=Decimal('0'),
        help_text='USD base price. Authoritative for the financial system; "price" is the legacy display value.',
    )
    time = models.PositiveIntegerField(default=0, help_text='Duration in minutes')
    is_active = models.BooleanField(default=True)
    category = models.ForeignKey(
        ServiceCategory,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='services',
    )
    compensation_role = models.CharField(
        max_length=20,
        choices=CompensationRole.choices,
        default=CompensationRole.NONE,
        help_text='Determines which staff role receives commission for this service',
    )

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['category', 'is_active'], name='svc_category_active_idx', condition=models.Q(is_active=True)),
            models.Index(fields=['name'], name='svc_name_idx'),
        ]

    def __str__(self):
        return self.name


class Customer(models.Model):
    first_name = models.CharField(max_length=100, validators=TEXT_SANITIZERS)
    last_name = models.CharField(max_length=100, validators=TEXT_SANITIZERS)
    mobile_number = models.CharField(max_length=20, unique=True, validators=TEXT_SANITIZERS)
    national_id = models.CharField(max_length=20, unique=True, validators=TEXT_SANITIZERS)
    bitmoji_code = models.CharField(max_length=50, unique=True, null=True, blank=True, validators=TEXT_SANITIZERS)
    file_sys_id = models.CharField(max_length=40, unique=True, null=True, blank=True, validators=TEXT_SANITIZERS)
    birthday = models.DateField(null=True, blank=True, help_text='Customer birthday (Shamsi YYYY-MM-DD via API)')
    created_at = models.DateTimeField(auto_now_add=True)
    satisfaction = models.PositiveSmallIntegerField(null=True, blank=True, help_text='Customer satisfaction rating 1-5')
    notes = models.TextField(blank=True, validators=TEXT_SANITIZERS)

    class Meta:
        ordering = ['first_name', 'last_name']

    def __str__(self):
        return f'{self.first_name} {self.last_name}'

    @property
    def full_name(self):
        return str(self)

    @property
    def visit_count(self):
        return self.visits.count()

    @property
    def is_new_customer(self):
        return self.visit_count == 0

    @property
    def is_loyal_customer(self):
        return self.visit_count >= 5

    @property
    def total_payments(self):
        from finance.models import Sale
        total = self.sales.filter(
            status__in=[Sale.Status.PAID, Sale.Status.REFUNDED, Sale.Status.PARTIALLY_REFUNDED],
        ).aggregate(total=models.Sum('amount_toman'))['total']
        return total or Decimal('0')

    @property
    def last_visit_date(self):
        last = self.visits.order_by('-start_at').first()
        if not last:
            return None
        from Sefro_Clinic.fields import greg_to_shamsi_date
        return greg_to_shamsi_date(last.start_at)

    @property
    def last_payment(self):
        return self.sales.order_by('-created_at').first()


class Visit(models.Model):
    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        CONFIRMED = 'confirmed', 'Confirmed'
        COMPLETED = 'completed', 'Completed'
        CANCELED = 'canceled', 'Canceled'

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name='visits')
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name='visits',
        null=True,
        blank=True,
    )
    services = models.ManyToManyField(Service, related_name='visits', through='VisitService')
    start_at = models.DateTimeField()
    end_at = models.DateTimeField()
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    notes = models.TextField(blank=True, validators=TEXT_SANITIZERS)

    class Meta:
        ordering = ['-start_at']
        indexes = [
            models.Index(fields=['start_at'], name='visits_start_at_idx'),
            models.Index(fields=['customer', 'start_at', 'end_at'], name='visit_overlap_idx'),
        ]

    def __str__(self):
        return f'{self.customer} - {self.start_at:%Y-%m-%d %H:%M}'

    def service_operator_map(self):
        """``{service_id: staff}`` for services with an assigned operator."""
        return {
            link.service_id: link.staff
            for link in self.service_links.select_related('staff').all()
            if link.staff_id
        }

    def resolved_operator_for(self, service):
        """Who performs one service on this visit.

        The per-service assignment (auto-resolved from the service's
        compensation role, or set explicitly through ``service_operators``)
        wins; the visit's primary ``staff`` is the legacy fallback.
        """
        service_id = getattr(service, 'id', service)
        link = self.service_links.select_related('staff').filter(service_id=service_id).first()
        if link is not None and link.staff_id:
            return link.staff
        return self.staff

    def resolve_operators(self):
        """Assign each of this visit's services the operator that performs it.

        Every service declares its operator role (``Service.compensation_role``).
        For each service without an assignment:

        * the primary ``staff`` is used when they hold the service's role;
        * otherwise a role with exactly one active operator is auto-assigned;
        * a role with no active operator and no assignment stays unresolved
          (the primary staff covers it only when nobody holds that role --
          the legacy behaviour when roles are not tagged on staff yet).

        When the visit has no primary staff, it is backfilled from the first
        assigned operator so visit-level reports keep one sensible key.

        Returns the roles still uncovered after assignment: a non-empty list
        means completing the visit would pay the wrong person (or nobody), so
        callers must reject it instead of silently generating no payout.
        """
        from accounts.models import ClinicUser

        links = list(self.service_links.select_related('service', 'staff').all())
        roles_needed = {
            link.service.compensation_role
            for link in links
            if link.service.compensation_role != Service.CompensationRole.NONE and not link.staff_id
        }

        candidates = {}
        if roles_needed:
            for user in ClinicUser.objects.filter(is_active=True, compensation_role__in=roles_needed):
                candidates.setdefault(user.compensation_role, []).append(user)

        changed = []
        for link in links:
            role = link.service.compensation_role
            if role == Service.CompensationRole.NONE or link.staff_id:
                continue
            pool = candidates.get(role, [])
            primary_match = (
                self.staff
                if self.staff_id and self.staff.compensation_role == role
                else None
            )
            chosen = primary_match or (pool[0] if len(pool) == 1 else None)
            if chosen is not None:
                link.staff = chosen
                changed.append(link)
        if changed:
            VisitService.objects.bulk_update(changed, ['staff'])

        if self.staff_id is None:
            first = next(
                (link.staff for link in links if link.staff_id),
                changed[0].staff if changed else None,
            )
            if first is not None:
                self.staff = first
                Visit.objects.filter(pk=self.pk).update(staff=first)

        # Coverage: a compensable service is paid to its assigned operator, or
        # to the primary staff only when nobody holds that role (legacy) or
        # the primary staff itself holds it.
        uncovered = []
        holders = set()
        role_links = [
            link for link in links
            if link.service.compensation_role != Service.CompensationRole.NONE
        ]
        compensable_roles = {link.service.compensation_role for link in role_links}
        if compensable_roles:
            holders = set(
                ClinicUser.objects.filter(
                    is_active=True, compensation_role__in=compensable_roles,
                ).values_list('compensation_role', flat=True)
            )
        for role in sorted(compensable_roles):
            assigned = any(
                link.service.compensation_role == role and link.staff_id
                for link in role_links
            )
            if assigned:
                continue
            if self.staff_id and (role not in holders or self.staff.compensation_role == role):
                continue
            uncovered.append(role)
        return uncovered


class VisitService(models.Model):
    """One service on a visit, with the operator who performs it.

    The ``Visit``/``Service`` many-to-many runs *through* this row: the
    compensation role lives on the service, so the visit resolves the actual
    person per service instead of paying every service to one primary staff.
    ``staff`` is NULL until assigned (explicitly through the API or by
    ``Visit.resolve_operators``); the visit's primary ``staff`` remains the
    fallback for legacy/untagged flows.
    """

    visit = models.ForeignKey(Visit, on_delete=models.CASCADE, related_name='service_links')
    service = models.ForeignKey(Service, on_delete=models.PROTECT, related_name='visit_links')
    staff = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='visit_service_assignments',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'customers_visitservice'
        constraints = [
            models.UniqueConstraint(fields=['visit', 'service'], name='uniq_visit_service_row'),
        ]
        indexes = [
            models.Index(fields=['staff'], name='visitservice_staff_idx'),
        ]

    def __str__(self):
        return f'{self.service} @ {self.visit_id} -> {self.staff or "unassigned"}'


