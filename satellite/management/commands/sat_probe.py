from django.core.management.base import BaseCommand, CommandError

from satellite import client


class Command(BaseCommand):
    help = "آزمون دسترسی: سرور ایران ← دروازه ← کاتالوگ و داده‌ی ماهواره (فاز ۰). روی خود سرور ایران اجرا شود."

    def handle(self, *args, **options):
        out = self.stdout.write
        if not client.configured():
            raise CommandError("SATGATE_URL و SATGATE_SECRET تنظیم نشده است.")
        out("۱) سلامت دروازه (بدون امضا)…")
        import json
        import time
        import urllib.request

        from django.conf import settings
        t = time.monotonic()
        try:
            with urllib.request.urlopen(settings.SATGATE_URL + "/v1/health", timeout=10) as r:  # noqa: S310
                info = json.loads(r.read())
        except OSError as exc:
            raise CommandError(f"به دروازه نرسیدیم ({exc}). فایروال، پورت و آدرس را بررسی کنید.") from exc
        out(f"   ok، نسخه‌ی {info.get('version')}، {int((time.monotonic() - t) * 1000)} میلی‌ثانیه، "
            f"کلید تنظیم‌شده: {info.get('configured')}")
        out("۲) کلید مشترک و دسترسی دروازه به کاتالوگ و داده…")
        try:
            res = client.call("POST", "/v1/probe", {}, timeout=60)
        except client.GatewayError as exc:
            raise CommandError(str(exc)) from exc
        out(f"   کاتالوگ: {res.get('stac_ms')} ms، داده‌ی نمونه: {res.get('data_ms')} ms ({res.get('data_bytes', 0)} بایت)")
        if not res.get("ok"):
            raise CommandError(f"دروازه به منبع داده نرسید: {res.get('error', 'نامشخص')}")
        out("۳) دانلود از دروازه به سرور ایران: یک پیش‌نمایش نمونه…")
        scenes = client.call("POST", "/v1/search", {"bbox": [51.3, 35.7, 51.4, 35.8], "start": "2026-01-01",
                                                      "end": "2026-12-31", "max_cloud": 100, "limit": 1}).get("scenes", [])
        if scenes:
            t = time.monotonic()
            data = client.thumb(scenes[0]["collection"], scenes[0]["id"])
            out(f"   {len(data)} بایت در {int((time.monotonic() - t) * 1000)} میلی‌ثانیه")
        self.stdout.write(self.style.SUCCESS("همه‌ی مراحل موفق بود؛ دروازه آماده‌ی کار است."))
