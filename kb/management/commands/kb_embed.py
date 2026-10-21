from django.core.management.base import BaseCommand

from kb import embedding, vectors


class Command(BaseCommand):
    help = "ساخت embedding (pgvector) برای تکه‌های پایگاه دانش؛ ورودی جست‌وجوی معنایی دستیار هوشمند."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", help="همه تکه‌ها را دوباره بساز")
        parser.add_argument("--limit", type=int, default=None, help="حداکثر تعداد تکه در این اجرا")

    def handle(self, *args, force=False, limit=None, **options):
        from core.models import SiteSettings

        conf = SiteSettings.get()
        if not conf.assistant_key_ready:
            self.stdout.write("دستیار هوشمند تنظیم نشده؛ کاری انجام نشد.")
            return
        res = embedding.embed_pending(conf, force=force, limit=limit)
        total, done = vectors.stats(conf.assistant_embedding_model)
        self.stdout.write(f"embedded={res['embedded']} remaining={res['remaining']} coverage={done}/{total}")
        if res["error"]:
            self.stderr.write(res["error"])
