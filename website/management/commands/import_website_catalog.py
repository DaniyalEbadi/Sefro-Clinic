from django.core.management.base import BaseCommand, CommandError

from website.services.importer import import_website_catalog


class Command(BaseCommand):
    help = 'Fetch and import the public Baran Clinic website catalog into Site API v2.'

    def handle(self, *args, **options):
        try:
            result = import_website_catalog()
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(
            'Imported website catalog: '
            f'{result.services} services, {result.packages} packages, '
            f'{result.package_options} package price options, {result.products} products, '
            f'{result.team_members} team members, {result.testimonials} testimonials.'
        ))
