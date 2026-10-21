from django.core.management.base import BaseCommand, CommandError

from kb import loader


class Command(BaseCommand):
    help = "مقاله‌های kb/content را در پایگاه داده می‌سازد یا به‌روز می‌کند (مقاله‌های ویرایش‌شده در پنل دست‌نخورده می‌مانند)."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="روی مقاله‌های قفل‌شده و دستی هم بنویس.")
        parser.add_argument("--prune", action="store_true", help="مقاله‌های حذف‌شده از فایل‌ها را پیش‌نویس کن.")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **opts):
        try:
            report = loader.sync(force=opts["force"], prune=opts["prune"], dry_run=opts["dry_run"])
        except loader.ContentError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(report.summary())
        for label, items in (("قفل", report.locked), ("تداخل", report.foreign)):
            if items:
                self.stdout.write(f"  {label}: {', '.join(items)}")
