from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from kernel import pkg


class Command(BaseCommand):
    help = "بسته‌ی پلاگین را مثل پنل (با کلیدهای ناشر همین استقرار) بررسی می‌کند، بدون ذخیره."

    def add_arguments(self, parser):
        parser.add_argument("package")

    def handle(self, package, **options):
        ins = pkg.inspect(Path(package).read_bytes())
        for s in ins.steps:
            self.stdout.write(f"{'✓' if s.ok else '✗'} {s.stage}{': ' + s.detail if s.detail else ''}")
        if not ins.ok:
            raise CommandError("بسته معتبر نیست.")
        self.stdout.write(f"ناشر: {ins.publisher}؛ {ins.manifest['id']} {ins.manifest['version']}؛ {len(ins.pages)} صفحه")
