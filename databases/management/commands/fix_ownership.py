from django.core.management.base import BaseCommand

from databases.models import UserDatabase
from databases.provisioner import Provisioner, ProvisionError


class Command(BaseCommand):
    help = "جدول‌هایی که کنسول SQL قدیمی با نقش مرورگر ساخته را به مالکیت کاربر برمی‌گرداند (یک بار اجرا کافی است)."

    def handle(self, *args, **options):
        fixed = failed = 0
        for db in UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES).select_related("server"):
            try:
                Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)
                fixed += 1
            except ProvisionError as exc:
                failed += 1
                self.stderr.write(f"{db.db_name}: {exc}")
        self.stdout.write(f"done: {fixed} ok, {failed} failed")
