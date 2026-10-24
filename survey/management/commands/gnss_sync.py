from django.core.management.base import BaseCommand

from survey.gnss import registry


class Command(BaseCommand):
    help = "درایورهای داخلی گیرنده GNSS را در جدول درایورها ثبت یا به‌روز می‌کند (ایمن برای اجرای تکراری)."

    def handle(self, *args, **options):
        r = registry.sync()
        self.stdout.write(f"درایورها: {r['created']} جدید، {r['updated']} به‌روز")
