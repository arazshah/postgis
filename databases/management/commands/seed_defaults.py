from django.core.management.base import BaseCommand

from databases.defaults import seed


class Command(BaseCommand):
    help = "ایجاد افزونه‌ها و پلن رایگان پیش‌فرض (قابل اجرای چندباره)"

    def handle(self, *args, **options):
        seed()
        self.stdout.write(self.style.SUCCESS("داده‌های پیش‌فرض آماده است."))
