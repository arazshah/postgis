import os

from django.core.management.base import BaseCommand

from accounts.models import User, normalize_mobile


class Command(BaseCommand):
    help = "ساخت یا ارتقای ادمین از DJANGO_SUPERUSER_PHONE (رمز DJANGO_SUPERUSER_PASSWORD اختیاری است)"

    def handle(self, *args, **options):
        raw = os.environ.get("DJANGO_SUPERUSER_PHONE", "").strip()
        if not raw:
            self.stdout.write("DJANGO_SUPERUSER_PHONE not set; skipped")
            return
        phone = normalize_mobile(raw)
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or None
        user = User.objects.filter(phone=phone).first()
        if user:
            if not (user.is_staff and user.is_superuser):
                user.is_staff = user.is_superuser = True
                user.save(update_fields=["is_staff", "is_superuser"])
                self.stdout.write(self.style.SUCCESS(f"{phone} promoted to superuser"))
            else:
                self.stdout.write("superuser exists")
            return
        User.objects.create_superuser(phone, password)
        self.stdout.write(self.style.SUCCESS(f"superuser {phone} created"))
