"""Closed-period protection for the Django admin, kept importable without ``django.contrib.admin``.

``django.contrib.admin`` is not part of INSTALLED_APPS, so ``finance/admin.py``
is dormant (it is only ever imported if the admin app gets enabled). The guard
itself needs nothing from admin -- only ``obj._meta`` and the form-error type
-- so it lives here: testable today, and ready for the day the admin is turned
on.

The mixin refuses admin edits/deletes of ledger rows booked into a CLOSED
month, the same lock the service layer applies to the API. ``PeriodClosedError``
becomes a form ``ValidationError`` so the admin would show a readable message
instead of a 500.
"""
from django.core.exceptions import ValidationError

from .services.periods_guard import PeriodClosedError, ensure_open


class ClosedPeriodGuardAdminMixin:
    """Refuse admin edits/deletes of ledger rows booked into a CLOSED month."""

    closed_anchor_field = 'created_at'

    def _closed_guard(self, obj, action):
        moment = getattr(obj, self.closed_anchor_field, None)
        if moment is None:
            return
        try:
            ensure_open(
                moment, action=f'{action} {obj._meta.model_name}',
                user=getattr(self, '_request_user', None), object_repr=str(obj)[:200],
            )
        except PeriodClosedError as exc:
            raise ValidationError(str(exc)) from exc

    def save_model(self, request, obj, form, change):
        self._request_user = request.user
        self._closed_guard(obj, 'change')
        super().save_model(request, obj, form, change)

    def delete_model(self, request, obj):
        self._request_user = request.user
        self._closed_guard(obj, 'delete')
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        self._request_user = request.user
        for obj in queryset:
            self._closed_guard(obj, 'delete')
        super().delete_queryset(request, queryset)
