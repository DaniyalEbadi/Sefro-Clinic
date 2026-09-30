"""Explicit repair command for corrupted Visit start_at/end_at dates.

Safety:
  * Dry-run by default (--apply required to persist changes)
  * Requires explicit --start-at-shamsi OR --start-at-iso for the new values
  * Optional --expect-current-start-at guards against concurrent modifications
  * Preserves visit duration (end_at - start_at) when only start_at is given

Usage:
    # Dry-run (preview only)
    python manage.py repair_visit_start_at 34 --start-at-shamsi "1405-07-08 14:03"

    # Apply with guard
    python manage.py repair_visit_start_at 34 --start-at-shamsi "1405-07-08 14:03" \\
        --expect-current-start-at "2647-12-19T14:03:00+00:00" --apply

    # Using ISO Gregorian datetime (explicit)
    python manage.py repair_visit_start_at 34 --start-at-iso "2026-09-28T14:03:00+03:30" --apply

Note:
  The old corruption occurred when a Gregorian date was silently interpreted
  as a Jalali date. This command requires an EXPLICIT target datetime (Shamsi
  or ISO) so the operator must verify the intended date from reliable sources
  (audit logs, reservation records, linked payments) before applying.
"""
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from customers.models import Visit
from Sefro_Clinic.fields import shamsi_to_greg_dt


class Command(BaseCommand):
    help = 'Repair a Visit start_at/end_at with an explicitly provided datetime (dry-run by default).'

    def add_arguments(self, parser):
        parser.add_argument('visit_id', type=int, help='Visit ID to repair.')
        parser.add_argument(
            '--start-at-shamsi',
            type=str,
            help='New start_at as Jalali datetime string "YYYY-MM-DD HH:MM" (e.g. "1405-07-08 14:03").',
        )
        parser.add_argument(
            '--start-at-iso',
            type=str,
            help='New start_at as ISO 8601 Gregorian datetime with offset (e.g. "2026-09-28T14:03:00+03:30").',
        )
        parser.add_argument(
            '--end-at-shamsi',
            type=str,
            help='Optional new end_at as Jalali datetime (if not given, duration is preserved).',
        )
        parser.add_argument(
            '--end-at-iso',
            type=str,
            help='Optional new end_at as ISO 8601 Gregorian datetime (if not given, duration is preserved).',
        )
        parser.add_argument(
            '--expect-current-start-at',
            type=str,
            help='ISO datetime that the current start_at must match, else abort (concurrency guard).',
        )
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Persist changes (without this flag the command is a dry-run).',
        )
        parser.add_argument(
            '--output',
            choices=['text', 'json'],
            default='text',
            help='Output format.',
        )

    def _parse_shamsi_dt(self, s):
        try:
            return shamsi_to_greg_dt(s)
        except Exception as e:
            raise CommandError(f'Invalid Shamsi datetime "{s}": {e}')

    def _parse_iso_dt(self, s):
        try:
            dt = datetime.fromisoformat(s)
        except ValueError as e:
            raise CommandError(f'Invalid ISO datetime "{s}": {e}')
        if timezone.is_naive(dt):
            raise CommandError(f'ISO datetime must include timezone offset: {s}')
        return dt

    def handle(self, *args, **options):
        visit_id = options['visit_id']
        start_shamsi = options['start_at_shamsi']
        start_iso = options['start_at_iso']
        end_shamsi = options['end_at_shamsi']
        end_iso = options['end_at_iso']
        expect_current = options['expect_current_start_at']
        apply = options['apply']
        output_json = options['output'] == 'json'

        if not start_shamsi and not start_iso:
            raise CommandError('One of --start-at-shamsi or --start-at-iso is required.')

        try:
            visit = Visit.objects.select_related('customer', 'staff').prefetch_related('services').get(id=visit_id)
        except Visit.DoesNotExist:
            raise CommandError(f'Visit {visit_id} does not exist.')

        # Optional guard
        if expect_current:
            try:
                expected = datetime.fromisoformat(expect_current)
                if timezone.is_naive(expected):
                    expected = timezone.make_aware(expected)
            except ValueError as e:
                raise CommandError(f'--expect-current-start-at must be ISO with offset: {e}')
            if visit.start_at != expected:
                raise CommandError(
                    f'Guard failed: current start_at is {visit.start_at.isoformat()}, '
                    f'expected {expected.isoformat()}. Aborted.'
                )

        # Parse new values
        if start_shamsi:
            new_start = self._parse_shamsi_dt(start_shamsi)
            if timezone.is_naive(new_start):
                new_start = timezone.make_aware(new_start)
        else:
            new_start = self._parse_iso_dt(start_iso)

        if end_shamsi:
            new_end = self._parse_shamsi_dt(end_shamsi)
            if timezone.is_naive(new_end):
                new_end = timezone.make_aware(new_end)
        elif end_iso:
            new_end = self._parse_iso_dt(end_iso)
        else:
            # Preserve duration
            duration = visit.end_at - visit.start_at
            new_end = new_start + duration

        if new_end <= new_start:
            raise CommandError('end_at must be after start_at.')

        result = {
            'visit_id': visit.id,
            'customer_id': visit.customer_id,
            'customer_name': f'{visit.customer.first_name} {visit.customer.last_name}',
            'old_start_at': visit.start_at.isoformat() if visit.start_at else None,
            'old_end_at': visit.end_at.isoformat() if visit.end_at else None,
            'new_start_at': new_start.isoformat(),
            'new_end_at': new_end.isoformat(),
            'duration_minutes': int((new_end - new_start).total_seconds() // 60),
            'applied': apply,
        }

        if apply:
            visit.start_at = new_start
            visit.end_at = new_end
            visit.save(update_fields=['start_at', 'end_at'])
            self.stdout.write(self.style.SUCCESS(f'Applied changes to Visit {visit_id}'))
        else:
            self.stdout.write(self.style.WARNING('DRY-RUN (use --apply to persist)'))

        if output_json:
            import json
            self.stdout.write(json.dumps(result, indent=2, default=str))
        else:
            self.stdout.write(f"  Visit: #{visit.id} ({result['customer_name']})")
            self.stdout.write(f"  Old start_at: {result['old_start_at']}")
            self.stdout.write(f"  Old end_at:   {result['old_end_at']}")
            self.stdout.write(f"  New start_at: {result['new_start_at']}")
            self.stdout.write(f"  New end_at:   {result['new_end_at']}")
            self.stdout.write(f"  Duration:     {result['duration_minutes']} minutes")
            self.stdout.write(f"  Applied:      {result['applied']}")
