"""Per-service operator assignment on visits (auto-resolution + attribution).

A visit with several services used to pay everything to one primary staff
member. Each service now declares its operator role and the visit figures out
who performs each service: explicit ``service_operators`` wins, otherwise the
primary staff is used when they hold the role, otherwise a role with exactly
one active holder is auto-assigned. Completion is rejected while a
compensable service would pay nobody.

Also guards the two report surfaces that must follow the same attribution:
``profit-by-staff`` (per-service rows) and ``operator_attribution``
(monthly-close operator rows).
"""
from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from accounts.models import ClinicUser
from customers.models import Service, Visit, VisitService
from finance.models import PaymentComponent, Sale, StaffCompensationRule, StaffPayout
from finance.services import financials
from finance.services.exchange_rates import set_rate
from tests.helpers import admin_client, make_customer, make_employee

RATE = Decimal('100000')
PROFIT_BY_STAFF_URL = '/api/finance/reports/profit-by-staff/'
COVERAGE_URL = '/api/finance/reports/profit-by-staff/coverage/'


def window():
    return timezone.now() - timedelta(days=1), timezone.now() + timedelta(days=1)


def make_rule(role=StaffCompensationRule.Role.DOCTOR, **overrides):
    base = {
        'role': role,
        'payout_type': StaffCompensationRule.PayoutType.CASH,
        'calculation_type': StaffCompensationRule.CalculationType.PERCENT_REVENUE,
        'percent_revenue': Decimal('50.00'),
    }
    base.update(overrides)
    # The default rules ship in a data migration; adjust in place.
    rule, _ = StaffCompensationRule.objects.get_or_create(role=role)
    for field, value in base.items():
        if field != 'role':
            setattr(rule, field, value)
    rule.save()
    return rule


class OperatorFixtureMixin:
    def setUp(self):
        set_rate('USD', 'TOMAN', RATE)
        self.client = admin_client()
        self.customer = make_customer()
        self.doctor = self._tagged('doc_user', ClinicUser.CompensationRole.DOCTOR)
        self.facialist = self._tagged('face_user', ClinicUser.CompensationRole.FACIAL)
        self.doctor_service = self._service(
            'Botox', Service.CompensationRole.DOCTOR, Decimal('200'),
        )
        self.facial_service = self._service(
            'Hydra', Service.CompensationRole.FACIAL, Decimal('100'),
        )

    def _tagged(self, username, role):
        user = make_employee(username=username)
        ClinicUser.objects.filter(pk=user.pk).update(compensation_role=role)
        user.refresh_from_db()
        return user

    def _service(self, name, role, price):
        return Service.objects.create(
            name=name, price_usd=price, compensation_role=role,
        )

    def _visit(self, services, staff=None, status=Visit.Status.CONFIRMED):
        visit = Visit.objects.create(
            customer=self.customer, staff=staff,
            start_at=timezone.now(), end_at=timezone.now() + timedelta(hours=1),
            status=status,
        )
        visit.services.set(services)
        return visit

    def _complete(self, visit):
        return self.client.post(f'/api/visits/{visit.id}/complete/')

    def _untag_all(self):
        """Nobody holds a compensation role (the pre-tagging world)."""
        ClinicUser.objects.filter(
            compensation_role__in=[
                ClinicUser.CompensationRole.DOCTOR,
                ClinicUser.CompensationRole.FACIAL,
                ClinicUser.CompensationRole.LASER,
            ],
        ).update(compensation_role=ClinicUser.CompensationRole.NONE)

    def _link(self, visit, service):
        return visit.service_links.get(service=service)


class AutoResolutionTests(OperatorFixtureMixin, TestCase):
    def test_unique_role_holder_is_auto_assigned_and_backfills_primary(self):
        visit = self._visit([self.doctor_service], staff=None)

        self.assertEqual(visit.resolve_operators(), [])

        link = self._link(visit, self.doctor_service)
        self.assertEqual(link.staff_id, self.doctor.id)
        visit.refresh_from_db()
        self.assertEqual(visit.staff_id, self.doctor.id)

    def test_ambiguous_role_is_not_auto_assigned_and_stays_uncovered(self):
        self._tagged('doc_user2', ClinicUser.CompensationRole.DOCTOR)
        visit = self._visit([self.doctor_service], staff=None)

        self.assertEqual(visit.resolve_operators(), [Service.CompensationRole.DOCTOR])
        self.assertIsNone(self._link(visit, self.doctor_service).staff_id)
        visit.refresh_from_db()
        self.assertIsNone(visit.staff_id)

    def test_primary_staff_holding_the_role_is_preferred(self):
        other = self._tagged('doc_user2', ClinicUser.CompensationRole.DOCTOR)
        visit = self._visit([self.doctor_service], staff=self.doctor)

        self.assertEqual(visit.resolve_operators(), [])
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, self.doctor.id)
        self.assertNotEqual(self.doctor.id, other.id)

    def test_mixed_visit_resolves_both_operators(self):
        visit = self._visit(
            [self.doctor_service, self.facial_service], staff=self.doctor,
        )

        self.assertEqual(visit.resolve_operators(), [])
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, self.doctor.id)
        self.assertEqual(self._link(visit, self.facial_service).staff_id, self.facialist.id)
        visit.refresh_from_db()
        self.assertEqual(visit.staff_id, self.doctor.id)

    def test_untagged_users_keep_the_legacy_primary_fallback(self):
        """No one holds a role yet: primary staff covers everything (no error)."""
        self._untag_all()
        plain = make_employee(username='plain_user')
        visit = self._visit([self.doctor_service, self.facial_service], staff=plain)

        self.assertEqual(visit.resolve_operators(), [])
        self.assertIsNone(self._link(visit, self.doctor_service).staff_id)
        self.assertIsNone(self._link(visit, self.facial_service).staff_id)
        self.assertEqual(visit.resolved_operator_for(self.doctor_service), plain)

    def test_existing_assignment_is_not_reassigned(self):
        visit = self._visit([self.doctor_service], staff=None)
        VisitService.objects.filter(visit=visit, service=self.doctor_service).update(
            staff=self.doctor,
        )

        self.assertEqual(visit.resolve_operators(), [])
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, self.doctor.id)


class SerializerTests(OperatorFixtureMixin, TestCase):
    def _create_visit(self, services, operators=None, staff=None):
        from Sefro_Clinic.fields import greg_to_shamsi_dt

        payload = {
            'customer': self.customer.id,
            'staff': staff.id if staff else None,
            'start_at': greg_to_shamsi_dt(timezone.now() + timedelta(days=1)),
            'end_at': greg_to_shamsi_dt(timezone.now() + timedelta(days=2)),
            'services': [service.id for service in services],
        }
        if operators is not None:
            payload['service_operators'] = operators
        return self.client.post('/api/visits/', payload, format='json')

    def test_create_visit_with_explicit_operators(self):
        response = self._create_visit(
            [self.doctor_service],
            operators=[{'service': self.doctor_service.id, 'staff': self.doctor.id}],
        )
        self.assertEqual(response.status_code, 201, response.data)
        visit = Visit.objects.get(pk=response.data['id'])
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, self.doctor.id)

    def test_explicit_operator_must_hold_the_service_role(self):
        response = self._create_visit(
            [self.doctor_service],
            operators=[{'service': self.doctor_service.id, 'staff': self.facialist.id}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('service_operators', response.data)

    def test_explicit_operator_service_must_be_on_the_visit(self):
        response = self._create_visit(
            [self.doctor_service],
            operators=[{'service': self.facial_service.id, 'staff': self.facialist.id}],
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn('service_operators', response.data)

    def test_explicit_operator_wins_when_auto_resolution_is_ambiguous(self):
        self._tagged('doc_user2', ClinicUser.CompensationRole.DOCTOR)
        second = ClinicUser.objects.get(username='doc_user2')
        response = self._create_visit(
            [self.doctor_service],
            operators=[{'service': self.doctor_service.id, 'staff': second.id}],
            staff=second,
        )
        self.assertEqual(response.status_code, 201, response.data)
        visit = Visit.objects.get(pk=response.data['id'])
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, second.id)

    def test_patch_replaces_assignments_and_reads_back(self):
        visit = self._visit([self.doctor_service], staff=self.doctor)
        visit.resolve_operators()
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, self.doctor.id)

        second = self._tagged('doc_user2', ClinicUser.CompensationRole.DOCTOR)
        response = self.client.patch(
            f'/api/visits/{visit.id}/',
            {'service_operators': [
                {'service': self.doctor_service.id, 'staff': second.id},
            ]},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(self._link(visit, self.doctor_service).staff_id, second.id)
        detail = self.client.get(f'/api/visits/{visit.id}/')
        operators = detail.data['operators']
        self.assertEqual(
            [(row['service'], row['staff']) for row in operators],
            [(self.doctor_service.id, second.id)],
        )


class CompletionAndPayoutTests(OperatorFixtureMixin, TestCase):
    def test_mixed_visit_pays_each_operator_for_their_own_service(self):
        make_rule(StaffCompensationRule.Role.DOCTOR, percent_revenue=Decimal('50.00'))
        make_rule(StaffCompensationRule.Role.FACIAL, percent_revenue=Decimal('40.00'))
        visit = self._visit(
            [self.doctor_service, self.facial_service], staff=self.doctor,
        )
        visit.resolve_operators()

        response = self._complete(visit)
        self.assertEqual(response.status_code, 200, response.data)

        payouts = {p.staff_id: p for p in StaffPayout.objects.all()}
        self.assertEqual(set(payouts), {self.doctor.id, self.facialist.id})
        # Doctor: 50% of the $200 botox; facial: 40% of the $100 hydra.
        self.assertEqual(payouts[self.doctor.id].payout_cash_usd, Decimal('100.00'))
        self.assertEqual(payouts[self.facialist.id].payout_cash_usd, Decimal('40.00'))

    def test_completion_is_rejected_while_a_role_is_uncovered(self):
        make_rule()
        self._tagged('doc_user2', ClinicUser.CompensationRole.DOCTOR)
        visit = self._visit([self.doctor_service], staff=None)

        response = self._complete(visit)
        self.assertEqual(response.status_code, 400)
        self.assertIn('doctor', response.data['error'])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_completion_still_rejected_without_any_staff_or_operator(self):
        # No tagged user holds the role and no primary staff exists: this is
        # the legacy failure mode and must stay a 400.
        self._untag_all()
        make_rule()
        visit = self._visit([self.doctor_service], staff=None)

        response = self._complete(visit)
        self.assertEqual(response.status_code, 400)
        self.assertIn('staff', response.data['error'])
        self.assertEqual(StaffPayout.objects.count(), 0)

    def test_untagged_legacy_visit_pays_the_primary_staff(self):
        self._untag_all()
        make_rule()
        plain = make_employee(username='plain_user')
        visit = self._visit([self.doctor_service], staff=plain)

        response = self._complete(visit)
        self.assertEqual(response.status_code, 200, response.data)
        payout = StaffPayout.objects.get()
        self.assertEqual(payout.staff_id, plain.id)
        self.assertEqual(payout.payout_cash_usd, Decimal('100.00'))


class ReportAttributionTests(OperatorFixtureMixin, TestCase):
    def _sale_on(self, visit, amount_usd):
        sale = Sale.objects.create(
            customer=self.customer, visit=visit, amount_usd=amount_usd,
            amount_toman=amount_usd * RATE, status=Sale.Status.PAID,
            exchange_rate=RATE,
        )
        PaymentComponent.objects.create(
            sale=sale, method=PaymentComponent.Method.CASH_TOMAN,
            amount_usd=amount_usd,
        )
        return sale

    def _mixed_visit(self):
        visit = self._visit(
            [self.doctor_service, self.facial_service], staff=self.doctor,
            status=Visit.Status.COMPLETED,
        )
        visit.resolve_operators()
        self._sale_on(visit, Decimal('300.00'))
        return visit

    def test_profit_by_staff_splits_a_mixed_visit_across_operators(self):
        self._mixed_visit()

        response = self.client.get(PROFIT_BY_STAFF_URL)
        self.assertEqual(response.status_code, 200, response.data)
        rows = {row['staff_id']: row for row in response.data}

        self.assertIn(self.doctor.id, rows)
        self.assertIn(self.facialist.id, rows)
        # $300 sale split by list price 200:100.
        self.assertEqual(Decimal(rows[self.doctor.id]['revenue_usd']), Decimal('200.00'))
        self.assertEqual(Decimal(rows[self.facialist.id]['revenue_usd']), Decimal('100.00'))
        # Each operator performed one service line of the same visit.
        self.assertEqual(rows[self.doctor.id]['visit_count'], 1)
        self.assertEqual(rows[self.facialist.id]['visit_count'], 1)

    def test_profit_by_staff_coverage_counts_operator_assigned_visits(self):
        # staffless but auto-assignable: attributed, not "unassigned".
        assignable = self._visit(
            [self.doctor_service], staff=None, status=Visit.Status.COMPLETED,
        )
        assignable.resolve_operators()
        # staffless and nothing assignable: unattributed.
        plain_service = self._service(
            'Peel', Service.CompensationRole.NONE, Decimal('50'),
        )
        self._visit([plain_service], staff=None, status=Visit.Status.COMPLETED)

        response = self.client.get(COVERAGE_URL)
        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data['total_visits'], 2)
        self.assertEqual(response.data['visits_with_staff'], 1)
        self.assertEqual(response.data['unassigned_visits'], 1)

    def test_operator_attribution_keys_monthly_close_rows_by_service_operator(self):
        self._mixed_visit()
        start, end = window()
        totals = {
            'revenue': {'usd': Decimal('300.00'), 'toman': Decimal('30000000.00')},
            'product_cost': {'usd': Decimal('0'), 'toman': Decimal('0')},
        }

        rows = financials.operator_attribution(start, end, totals=totals)

        self.assertEqual(rows[self.doctor.id]['revenue_usd'], Decimal('200.00'))
        self.assertEqual(rows[self.facialist.id]['revenue_usd'], Decimal('100.00'))
        # Parts + residual sum back to the whole exactly.
        attributed = sum((row['revenue_usd'] for row in rows.values()), Decimal('0'))
        self.assertEqual(attributed, totals['revenue']['usd'])

    def test_reports_still_sum_to_the_financial_summary(self):
        self._mixed_visit()
        start, end = window()

        report = financials.build_report(start, end)
        attribution = financials.operator_attribution(start, end, totals=report)

        attributed = sum(
            (row['revenue_usd'] for row in attribution.values()), Decimal('0'),
        )
        self.assertEqual(attributed, report['revenue']['usd'])


class RoleIsolationTests(OperatorFixtureMixin, TestCase):
    """The role axes must not leak into each other.

    ``Customer`` is an end client (not a user), ``ClinicUser.role`` controls
    permissions, ``ClinicUser.compensation_role`` only controls money. The
    employees API is the only writer of the money axis and it is admin-only.
    """

    def test_customer_model_has_no_user_or_role_fields(self):
        from customers.models import Customer

        field_names = {field.name for field in Customer._meta.get_fields()}
        self.assertNotIn('role', field_names)
        self.assertNotIn('compensation_role', field_names)
        self.assertNotIn('is_superuser', field_names)

    def test_role_and_compensation_role_are_independent_fields(self):
        field_names = {field.name for field in ClinicUser._meta.get_fields()}
        self.assertIn('role', field_names)
        self.assertIn('compensation_role', field_names)
        # Setting one never touches the other.
        user = make_employee(username='role_iso_user')
        ClinicUser.objects.filter(pk=user.pk).update(
            compensation_role=ClinicUser.CompensationRole.LASER,
        )
        user.refresh_from_db()
        self.assertEqual(user.role, ClinicUser.Role.EMPLOYEE)
        self.assertEqual(user.compensation_role, ClinicUser.CompensationRole.LASER)
        self.assertFalse(user.is_superuser)
        self.assertFalse(user.is_staff)

    def test_admin_can_set_compensation_role_on_an_employee(self):
        target = make_employee(username='role_target')
        response = self.client.patch(
            f'/api/auth/employees/{target.id}/',
            {'compensation_role': ClinicUser.CompensationRole.DOCTOR},
            format='json',
        )
        self.assertEqual(response.status_code, 200, response.data)
        target.refresh_from_db()
        self.assertEqual(target.compensation_role, ClinicUser.CompensationRole.DOCTOR)

    def test_employee_cannot_edit_employee_roles(self):
        from tests.helpers import employee_client

        target = make_employee(username='role_target')
        employee = employee_client(username='emp_user')
        response = employee.patch(
            f'/api/auth/employees/{target.id}/',
            {'compensation_role': ClinicUser.CompensationRole.DOCTOR},
            format='json',
        )
        self.assertIn(response.status_code, (403, 404))
        target.refresh_from_db()
        self.assertEqual(
            target.compensation_role, ClinicUser.CompensationRole.NONE,
        )
