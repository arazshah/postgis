from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from kernel import extpurge


class Command(BaseCommand):
    help = ("پاک‌سازی صریح داده‌ی پلاگین سطح ۳ حذف‌شده: جدول‌های x_<id>_* و ردیف‌های django_migrations همان برچسب. "
            "بدون --yes فقط نشان می‌دهد؛ اگر پلاگین هنوز نصب است رد می‌کند. پیش از آن پشتیبان بگیرید.")

    def add_arguments(self, parser):
        parser.add_argument("plugin")
        parser.add_argument("--yes", action="store_true", help="واقعاً پاک کن")
        parser.add_argument("--root", help="پوشه‌ی ext جایگزین (آزمون)")

    def handle(self, plugin, yes=False, root=None, **options):
        try:
            p = extpurge.plan(plugin, Path(root) if root else None)
            self.stdout.write(f"جدول‌ها: {', '.join(p['tables']) or '—'}")
            self.stdout.write(f"مهاجرت‌ها: {p['migrations_app'] or '—'}")
            if not yes:
                self.stdout.write("پیش‌نمایش بود؛ برای پاک‌کردن --yes بدهید (پیش از آن پشتیبان بگیرید).")
                return
            extpurge.execute(plugin, Path(root) if root else None)
        except extpurge.PurgeError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write("پاک شد.")
