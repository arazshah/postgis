import json
import sys

from django.core.management.base import BaseCommand, CommandError

from kb import export


class Command(BaseCommand):
    help = ("خروجی ماشین‌خوان پایگاه دانش برای دستیار هوشمند: مقاله‌ها یا تکه‌ها (JSONL)؛ "
            "توکن‌های پلن جایگزین و پیوندها مطلق می‌شوند.")

    def add_arguments(self, parser):
        parser.add_argument("--audience", choices=["public", "member", "all"], default="public",
                            help="public فقط عمومی؛ member عمومی و کاربران؛ all شامل مستندات داخلی.")
        parser.add_argument("--format", choices=["chunks", "articles"], default="chunks")
        parser.add_argument("--out", help="مسیر فایل؛ پیش‌فرض خروجی استاندارد.")

    def handle(self, *args, **opts):
        rows = (export.chunk_rows if opts["format"] == "chunks" else export.article_rows)(opts["audience"])
        out = open(opts["out"], "w", encoding="utf-8") if opts["out"] else sys.stdout  # noqa: SIM115
        try:
            n = 0
            for r in rows:
                out.write(json.dumps(r, ensure_ascii=False) + "\n")
                n += 1
        except OSError as exc:
            raise CommandError(str(exc)) from exc
        finally:
            if opts["out"]:
                out.close()
        self.stderr.write(f"{n} ردیف نوشته شد.")
