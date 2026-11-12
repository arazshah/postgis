from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from kernel import extcheck, extnew


class Command(BaseCommand):
    help = "داربست پلاگین سطح ۳ در ext/<id> (apps، plugin، مدل نمونه، مهاجرت، نما، قالب، آزمون، README)."

    def add_arguments(self, parser):
        parser.add_argument("plugin", help="شناسه‌ی پلاگین (حرف کوچک، عدد، _)")
        parser.add_argument("--name", default="", help="نام نمایشی فارسی")
        parser.add_argument("--root", help="پوشه‌ی ext جایگزین (آزمون)")

    def handle(self, plugin, name="", root=None, **options):
        base = Path(root) if root else Path(settings.BASE_DIR) / "ext"
        try:
            made = extnew.scaffold(base, plugin, name)
        except extnew.ScaffoldError as exc:
            raise CommandError(str(exc)) from exc
        bad = [f for f in extcheck.check_plugin(base / plugin) if f.level == "error"]
        if bad:  # نباید رخ دهد؛ اگر داد یعنی قالب با قاعده‌ها ناسازگار شده
            raise CommandError("داربست از ext_check نگذشت: " + "؛ ".join(str(f) for f in bad))
        self.stdout.write(f"{len(made)} فایل در {base / plugin} ساخته شد.")
        self.stdout.write(f"گام بعد: python manage.py ext_check {plugin} ؛ python manage.py test ext.{plugin}")
