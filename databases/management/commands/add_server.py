import os

from django.core.management.base import BaseCommand, CommandError

from databases import services
from databases.models import DatabaseServer


class Command(BaseCommand):
    help = "افزودن/به‌روزرسانی یک سرور دیتابیس از خط فرمان. رمز از متغیر محیطی PG_ADMIN_PASSWORD خوانده می‌شود."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--host", required=True)
        parser.add_argument("--port", type=int, default=5432)
        parser.add_argument("--user", default="postgres")
        parser.add_argument("--public-host")
        parser.add_argument("--public-port", type=int)
        parser.add_argument("--sslmode", default="prefer")
        parser.add_argument("--public-sslmode", default="require")
        parser.add_argument("--default", action="store_true")

    def handle(self, *args, **o):
        password = os.environ.get("PG_ADMIN_PASSWORD")
        if not password:
            raise CommandError("PG_ADMIN_PASSWORD تنظیم نشده است.")
        server, _ = DatabaseServer.objects.get_or_create(name=o["name"], defaults={"host": o["host"],
                                                                                    "public_host": o["host"]})
        server.host = o["host"]
        server.port = o["port"]
        server.admin_user = o["user"]
        server.public_host = o["public_host"] or o["host"]
        server.public_port = o["public_port"] or o["port"]
        server.sslmode = o["sslmode"]
        server.public_sslmode = o["public_sslmode"]
        server.is_default = o["default"] or not DatabaseServer.objects.exclude(pk=server.pk).exists()
        server.set_admin_password(password)
        server.save()
        info = services.refresh_server(server, harden=True)
        self.stdout.write(("OK " if info.ok else "FAIL ") + info.message)
