from django.core.management.base import BaseCommand, CommandError

from satellite import probe


class Command(BaseCommand):
    help = "آزمون دسترسی: سرور ایران ← دروازه ← کاتالوگ و داده‌ی ماهواره (همان دکمه‌ی «آزمایش اتصال» در تنظیمات سایت)."

    def handle(self, *args, **options):
        steps = probe.run()
        for ok, text in steps:
            self.stdout.write(("✓ " if ok else "✗ ") + text)
        if not all(ok for ok, _ in steps):
            raise CommandError("آزمون ناموفق بود.")
        self.stdout.write(self.style.SUCCESS("همه‌ی مراحل موفق بود؛ دروازه آماده‌ی کار است."))
