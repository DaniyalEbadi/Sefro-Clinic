"""Keep the isolated Site API catalog aligned with USD four times a day."""

import time

from django.core.management.base import BaseCommand

from website.services.sync import sync_website_prices_if_due


class Command(BaseCommand):
    help = 'Sync website prices after 00:00, 06:00, 12:00, 18:00 Asia/Tehran; retry failures after 15 minutes.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Check the current window once and exit.')

    def handle(self, *args, **options):
        while True:
            try:
                run = sync_website_prices_if_due()
                if run is not None:
                    self.stdout.write(
                        f'Website price sync {run.status}: provider={run.provider}, '
                        f'rate={run.rate}, services={run.updated_services}, '
                        f'packages={run.updated_packages}, products={run.updated_products}'
                    )
            except Exception as exc:
                self.stderr.write(f'Website price scheduler error: {exc.__class__.__name__}: {exc}')
                if options['once']:
                    raise
            if options['once']:
                return
            time.sleep(60)
