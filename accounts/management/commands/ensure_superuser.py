import os

from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = "ساخت ادمین از DJANGO_SUPERUSER_EMAIL و DJANGO_SUPERUSER_PASSWORD اگر وجود نداشته باشد"

    def handle(self, *args, **options):
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "").strip().lower()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not email or not password:
            self.stdout.write("superuser env not set; skipped")
            return
        if User.objects.filter(email=email).exists():
            self.stdout.write("superuser exists")
            return
        User.objects.create_superuser(email, password)
        self.stdout.write(self.style.SUCCESS(f"superuser {email} created"))
