from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from kernel import extcheck


class Command(BaseCommand):
    help = "بررسی ایستای پلاگین‌های سطح ۳ در ext/ (ساختار، کد ممنوع، مهاجرت افزایشی)؛ با خطا کد خروج غیرصفر."

    def add_arguments(self, parser):
        parser.add_argument("plugin", nargs="?", help="شناسه‌ی یک پلاگین (پیش‌فرض: همه)")
        parser.add_argument("--root", help="پوشه‌ی ext جایگزین (آزمون)")

    def handle(self, plugin=None, root=None, **options):
        base = Path(root) if root else Path(settings.BASE_DIR) / "ext"
        results = extcheck.check_all(base, plugin)
        if plugin and plugin not in results:
            raise CommandError(f"پلاگین «{plugin}» در {base} پیدا نشد.")
        errors = 0
        for pid, findings in results.items():
            bad = [f for f in findings if f.level == "error"]
            errors += len(bad)
            self.stdout.write(f"{pid}: {'ناموفق' if bad else 'سالم'} ({len(bad)} خطا، {len(findings) - len(bad)} هشدار)")
            for f in findings:
                self.stdout.write(f"  {f}")
        if not results:
            self.stdout.write("پلاگینی در ext/ نیست.")
        if errors:
            raise CommandError(f"{errors} خطا؛ مرج/انتشار مجاز نیست.")
