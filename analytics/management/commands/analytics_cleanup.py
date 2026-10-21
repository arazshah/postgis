from django.core.management.base import BaseCommand

from analytics import services


class Command(BaseCommand):
    help = "پاک‌سازی داده خام آمار بازدید (پیش‌فرض ۹۰ روز)"

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=None)

    def handle(self, *args, days=None, **options):
        self.stdout.write(f"analytics cleanup: {services.cleanup(days)}")
