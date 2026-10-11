import os

from django.core.management.base import BaseCommand

from accounts.models import User


class Command(BaseCommand):
    help = ("ساخت مدیر اولیه از DJANGO_SUPERUSER_USERNAME و DJANGO_SUPERUSER_PASSWORD. "
            "اگر این نام کاربری وجود داشته باشد هیچ تغییری نمی‌دهد (رمزی که از پنل عوض کرده‌اید حفظ می‌شود).")

    def handle(self, *args, **options):
        username = os.environ.get("DJANGO_SUPERUSER_USERNAME", "").strip()
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD", "")
        if not username or not password:
            self.stdout.write("DJANGO_SUPERUSER_USERNAME/PASSWORD not set; skipped")
            return
        if User.objects.filter(username=username).exists():
            self.stdout.write(f"admin '{username}' exists; unchanged")
            return
        User.objects.create_admin(username, password, full_name="مدیر سایت")
        self.stdout.write(self.style.SUCCESS(f"admin '{username}' created"))
