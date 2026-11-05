from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from jobs import offsite


class Command(BaseCommand):
    help = ("رمزگشایی فایل بکاپ رمزنگاری‌شده‌ی فضای ابری (.enc) به فایل pg_dump معمولی، با همان "
            "CREDENTIALS_ENCRYPTION_KEY (یا SECRET_KEY) که هنگام ارسال بوده است.")

    def add_arguments(self, parser):
        parser.add_argument("source", help="مسیر فایل .enc دانلودشده از باکت")
        parser.add_argument("dest", help="مسیر فایل خروجی (.dump)")

    def handle(self, *args, source, dest, **options):
        src, dst = Path(source), Path(dest)
        if not src.is_file():
            raise CommandError(f"فایل پیدا نشد: {src}")
        try:
            offsite.decrypt_file(src, dst)
        except offsite.OffsiteError as exc:
            dst.unlink(missing_ok=True)
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"رمزگشایی شد: {dst}"))
