import getpass
import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction


class Command(BaseCommand):
    help = 'Create or update the AdminPapa Django superuser without storing the password in source code.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--password-env',
            default='ADMINPAPA_PASSWORD',
            help='Name of the environment variable containing the password.',
        )
        parser.add_argument(
            '--no-input',
            action='store_true',
            help='Fail if the password environment variable is not set.',
        )

    def handle(self, *args, **options):
        password_env = options['password_env']
        password = os.environ.get(password_env)

        if password is None and not options['no_input']:
            password = getpass.getpass('AdminPapa password: ')
            confirmation = getpass.getpass('Confirm AdminPapa password: ')
            if password != confirmation:
                raise CommandError('Passwords do not match.')

        if not password:
            raise CommandError(
                f'Provide the password through {password_env} or run without --no-input.'
            )

        User = get_user_model()
        with transaction.atomic():
            user, created = User.objects.get_or_create(username='AdminPapa')
            user.is_active = True
            user.is_staff = True
            user.is_superuser = True
            if hasattr(user, 'role'):
                user.role = 'super_admin'
            user.set_password(password)
            user.save(update_fields=['password', 'is_active', 'is_staff', 'is_superuser', 'role'] if hasattr(user, 'role') else ['password', 'is_active', 'is_staff', 'is_superuser'])

        action = 'created' if created else 'updated'
        self.stdout.write(self.style.SUCCESS(f'AdminPapa {action} as a Django superuser.'))
