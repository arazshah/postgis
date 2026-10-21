from django.core.management.base import BaseCommand, CommandError

from kb import loader


class Command(BaseCommand):
    help = "فایل‌های محتوای پایگاه دانش را بررسی می‌کند (سرایند، پیوندها، توکن‌ها، مقاله‌های مرتبط)."

    def handle(self, *args, **opts):
        problems = loader.validate()
        files = loader.load_articles()
        self.stdout.write(f"{len(files)} مقاله در {len({f.category for f in files})} دسته بررسی شد.")
        if problems:
            for p in problems:
                self.stderr.write(f"  ✗ {p}")
            raise CommandError(f"{len(problems)} مشکل پیدا شد.")
        self.stdout.write(self.style.SUCCESS("محتوا سالم است."))
