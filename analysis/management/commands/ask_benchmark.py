"""سنجش دقت پرسش فارسی با کلید مدل زبانی خودتان.

مثال:
    LLM_API_KEY=... python manage.py ask_benchmark --model gpt-4o
    python manage.py ask_benchmark --model gpt-4o-mini --no-values   # بدون مقدارهای ستون‌ها، برای مقایسه
"""
import os

from django.core.management.base import BaseCommand, CommandError

from analysis import benchmark


class Command(BaseCommand):
    help = "پرسش‌های فارسی با پاسخ درست را روی دادهٔ نمونه اجرا و دقت را گزارش می‌کند."

    def add_arguments(self, parser):
        parser.add_argument("--base-url", default=os.environ.get("LLM_BASE_URL", "https://api.avalai.ir/v1"))
        parser.add_argument("--model", default=os.environ.get("LLM_MODEL", "gpt-4o"))
        parser.add_argument("--key", default=os.environ.get("LLM_API_KEY", ""), help="یا متغیر LLM_API_KEY")
        parser.add_argument("--only", type=int, nargs="*", help="شمارهٔ پرسش‌هایی که اجرا شوند")
        parser.add_argument("--no-values", action="store_true", help="مقدارهای ستون‌ها را برای مدل نفرست")

    def handle(self, *args, **o):
        if not o["key"]:
            raise CommandError("کلید لازم است: --key یا LLM_API_KEY")
        from s3geo import OpenAICompatibleLLMClient

        client = OpenAICompatibleLLMClient(api_key=o["key"], base_url=o["base_url"], model=o["model"], timeout=90)
        qs = benchmark.load_questions()
        if o["only"]:
            qs = [q for i, q in enumerate(qs, 1) if i in o["only"]]

        def show(r):
            mark = "✓" if r["ok"] else "✗"
            self.stdout.write(f"{mark} {r['n']:>2} [{r['kind']:<6}] چشم‌داشت {r['expected']:<4} گرفت {r['got']:<4} "
                              f"تلاش {r['attempts']} {r['seconds']}s  {r['q'][:60]}"
                              + (f"\n      ↳ {r['error'][:140]}" if r["error"] and not r["ok"] else ""))

        rows = benchmark.run(client, qs, share_values=not o["no_values"], on_row=show)
        s = benchmark.summary(rows)
        self.stdout.write(f"\nدقت: {s['passed']}/{s['total']} ({s['accuracy']}٪) — درست در تلاش اول {s['first_try']}، "
                          f"درست پس از اصلاح {s['repaired']}، میانگین تلاش {s['avg_attempts']}")
