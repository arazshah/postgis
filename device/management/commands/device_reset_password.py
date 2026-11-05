"""بازنشانی رمز یک حساب دستگاه از راه SSH (وقتی مدیر رمزش را فراموش کرده): sudo pgpro-manage device_reset_password admin"""
from django.core.management.base import BaseCommand, CommandError

from accounts.models import User
from device import services


class Command(BaseCommand):
    help = "رمز حساب را به رمز موقت بازمی‌گرداند (پیش‌فرض: pgpro) و در اولین ورود تغییر رمز را اجباری می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("username", nargs="?", default=services.DEFAULT_ADMIN)
        parser.add_argument("--password", default=services.DEFAULT_PASSWORD)

    def handle(self, *args, username, password, **options):
        user = User.objects.filter(username=username.lower()).first()
        if user is None:
            raise CommandError(f"کاربری با نام «{username}» نیست.")
        user.is_active = True
        user.save(update_fields=["is_active"])
        services.set_password(user, password, must_change=True)
        self.stdout.write(self.style.SUCCESS(
            f"رمز «{user.username}» بازنشانی شد. در اولین ورود باید رمز تازه بگذارد."))
