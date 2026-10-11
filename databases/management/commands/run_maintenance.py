from django.core.management.base import BaseCommand

from databases import services
from databases.models import DatabaseServer


class Command(BaseCommand):
    help = "پایش حجم، انقضا و سلامت سرورها. در Coolify به‌صورت Scheduled Task هر ۱۰ دقیقه اجرا شود."

    def add_arguments(self, parser):
        parser.add_argument("--only", choices=["quota", "expiry", "servers", "billing"], help="فقط یک بخش اجرا شود")

    def handle(self, *args, only=None, **options):
        if only in (None, "servers"):
            for server in DatabaseServer.objects.all():
                info = services.refresh_server(server)
                self.stdout.write(f"server {server.name}: {'OK' if info.ok else 'FAIL'} {info.message}")
        if only in (None, "quota"):
            self.stdout.write(f"quota: {services.check_quotas()}")
        if only in (None, "expiry"):
            self.stdout.write(f"expiry: {services.process_expiry()}")
        if only in (None, "billing"):
            from billing.services import maintenance

            self.stdout.write(f"billing: {maintenance()}")
