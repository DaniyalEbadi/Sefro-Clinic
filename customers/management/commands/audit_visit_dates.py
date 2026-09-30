"""Read-only investigation command for suspicious Visit start_at dates.

Usage:
    python manage.py audit_visit_dates 34 35
    python manage.py audit_visit_dates --suspicious
    python manage.py audit_visit_dates --since 2100-01-01

Outputs: for each visit, customer, staff, services, status, created timestamp
(from audit log), and the stored start_at/end_at. Does NOT modify data.
"""
import json
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from customers.models import Visit
from logs.models import AuditLog


class Command(BaseCommand):
    help = 'Investigate Visit start_at dates; print audit trail and related data (read-only).'

    def add_arguments(self, parser):
        parser.add_argument('visit_ids', nargs='*', type=int, help='Specific visit IDs to inspect.')
        parser.add_argument(
            '--suspicious',
            action='store_true',
            help='Find all visits with start_at year >= 2100 (heuristic for corruption).',
        )
        parser.add_argument(
            '--since',
            type=str,
            help='ISO date (YYYY-MM-DD); inspect visits with start_at >= this date.',
        )
        parser.add_argument(
            '--output',
            choices=['text', 'json'],
            default='text',
            help='Output format.',
        )

    def handle(self, *args, **options):
        visit_ids = options['visit_ids']
        suspicious = options['suspicious']
        since_str = options['since']
        output_json = options['output'] == 'json'

        if not visit_ids and not suspicious and not since_str:
            raise CommandError('Provide visit IDs, or use --suspicious or --since.')

        qs = Visit.objects.select_related('customer', 'staff').prefetch_related('services')

        if visit_ids:
            qs = qs.filter(id__in=visit_ids)
            if len(visit_ids) != qs.count():
                missing = set(visit_ids) - set(qs.values_list('id', flat=True))
                self.stderr.write(self.style.WARNING(f'Visits not found: {sorted(missing)}'))

        if suspicious:
            qs = qs.filter(start_at__year__gte=2100)

        if since_str:
            try:
                since = datetime.fromisoformat(since_str)
                if timezone.is_naive(since):
                    since = timezone.make_aware(since)
            except ValueError as e:
                raise CommandError(f'--since must be ISO date (YYYY-MM-DD): {e}')
            qs = qs.filter(start_at__gte=since)

        visits = list(qs.order_by('id'))
        if not visits:
            self.stdout.write(self.style.NOTICE('No visits matched.'))
            return

        results = []
        for v in visits:
            # Fetch audit log entries for this visit
            audit_entries = list(
                AuditLog.objects.filter(model_name='customers.visit', object_id=str(v.id)).order_by('timestamp')
            )

            created_at = None
            created_changes = None
            for entry in audit_entries:
                if entry.action == 'CREATE':
                    created_at = entry.timestamp
                    created_changes = entry.changes
                    break

            result = {
                'visit': {
                    'id': v.id,
                    'customer_id': v.customer_id,
                    'customer_name': f'{v.customer.first_name} {v.customer.last_name}',
                    'staff_id': v.staff_id,
                    'staff_name': str(v.staff) if v.staff else None,
                    'services': [s.name for s in v.services.all()],
                    'status': v.status,
                    'start_at': v.start_at.isoformat() if v.start_at else None,
                    'end_at': v.end_at.isoformat() if v.end_at else None,
                },
                'audit': {
                    'created_at': created_at.isoformat() if created_at else None,
                    'created_changes': created_changes,
                    'entry_count': len(audit_entries),
                },
            }
            results.append(result)

        if output_json:
            self.stdout.write(json.dumps(results, indent=2, default=str))
        else:
            for r in results:
                v = r['visit']
                a = r['audit']
                self.stdout.write(self.style.HTTP_INFO(f"=== Visit #{v['id']} ==="))
                self.stdout.write(f"  Customer: {v['customer_name']} (id={v['customer_id']})")
                self.stdout.write(f"  Staff: {v['staff_name']} (id={v['staff_id']})")
                self.stdout.write(f"  Services: {', '.join(v['services']) if v['services'] else 'none'}")
                self.stdout.write(f"  Status: {v['status']}")
                self.stdout.write(f"  start_at: {v['start_at']}")
                self.stdout.write(f"  end_at: {v['end_at']}")
                if a['created_at']:
                    self.stdout.write(f"  Created (audit): {a['created_at']}")
                    if a['created_changes']:
                        start_at_in_changes = a['created_changes'].get('start_at')
                        if start_at_in_changes:
                            self.stdout.write(f"  start_at at creation: {start_at_in_changes}")
                else:
                    self.stdout.write(self.style.WARNING('  No CREATE audit log entry found'))
                if a['entry_count'] > 1:
                    self.stdout.write(f"  Total audit entries: {a['entry_count']}")
                self.stdout.write('')
