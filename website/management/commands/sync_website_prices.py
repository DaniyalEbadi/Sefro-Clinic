from django.core.management.base import BaseCommand, CommandError

from website.services.sync import sync_website_prices


class Command(BaseCommand):
    help = 'Refresh website catalog Toman prices from USD prices and the exchange-rate providers.'

    def handle(self, *args, **options):
        try:
            run = sync_website_prices()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        if run.status == run.Status.FAILED:
            raise CommandError(run.error)
        self.stdout.write(self.style.SUCCESS(
            f'Synced website prices with {run.rate} Toman/USD via {run.provider}: '
            f'{run.updated_services} services, {run.updated_packages} packages, '
            f'{run.updated_products} products.'
        ))
