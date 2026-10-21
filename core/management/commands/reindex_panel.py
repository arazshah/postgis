from django.core.management.base import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = ("بازسازی نمایه‌های دیتابیس پنل بعد از تعویض ایمیج PostgreSQL (alpine → Debian/pgvector)، چون ترتیب "
            "مرتب‌سازی متن‌ها بین musl و glibc فرق دارد. روی غیر PostgreSQL کاری نمی‌کند.")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("پایگاه داده PostgreSQL نیست؛ کاری لازم نیست.")
            return
        name = connection.settings_dict["NAME"]
        quoted = connection.ops.quote_name(name)
        connection.close()
        connection.ensure_connection()
        connection.connection.autocommit = True  # REINDEX DATABASE داخل تراکنش مجاز نیست
        try:
            with connection.cursor() as cur:
                cur.execute(f"REINDEX DATABASE {quoted}")
                try:
                    cur.execute(f"ALTER DATABASE {quoted} REFRESH COLLATION VERSION")
                except Exception:  # noqa: S110 — نسخه‌های قدیمی‌تر یا بدون هشدار collation
                    pass
        except Exception as exc:
            raise CommandError(f"REINDEX ناموفق بود: {exc}") from exc
        self.stdout.write(f"REINDEX DATABASE {name}: انجام شد.")
