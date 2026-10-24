"""Provision separate credentials for an existing clinic staff identity."""

import getpass
import os

from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from accounts.models import ClinicUser
from website.models import WebsiteManagerCredential


class Command(BaseCommand):
    help = 'Create or reset a website-dashboard login linked to an existing staff user.'

    def add_arguments(self, parser):
        parser.add_argument('--clinic-username', required=True)
        parser.add_argument('--website-username', required=True)
        parser.add_argument('--password-env', help='Name of an environment variable holding the new password.')

    def handle(self, *args, **options):
        try:
            user = ClinicUser.objects.get(username=options['clinic_username'], is_active=True)
        except ClinicUser.DoesNotExist as exc:
            raise CommandError('Active clinic staff user not found.') from exc
        website_username = options['website_username'].strip()
        if not website_username or website_username == user.username:
            raise CommandError('Website username must be non-empty and different from the clinic username.')
        variable = options['password_env']
        password = os.environ.get(variable, '') if variable else getpass.getpass('Website password: ')
        if not password or user.check_password(password):
            raise CommandError('Website password must be non-empty and different from the clinic password.')
        try:
            validate_password(password, user=user)
        except ValidationError as exc:
            raise CommandError(' '.join(exc.messages)) from exc
        with transaction.atomic():
            credential, _ = WebsiteManagerCredential.objects.get_or_create(
                user=user, defaults={'username': website_username},
            )
            credential.username = website_username
            credential.is_active = True
            credential.set_password(password)
            credential.save()
            credential.sessions.all().delete()  # Password reset revokes prior website sessions.
        self.stdout.write(self.style.SUCCESS(f'Website login ready for {website_username}.'))
