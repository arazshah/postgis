"""آماده‌سازی دستگاه pgpro (قابل اجرای چندباره): تنظیم سایت، پلن نامحدود، سرور PostgreSQL محلی، مدیر اولیه."""
import os

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand

from accounts.models import User
from core.models import SiteSettings
from databases.defaults import seed
from databases.models import DatabaseServer, Plan
from device import services

PLAN = {
    "slug": "pgpro", "name": "pgpro", "description": "پلن دستگاه: بدون سقف و بدون انقضا (محدودیت فقط فضای دستگاه است).",
    "quota_mb": 1_048_576, "max_connections": 20, "duration_days": 36500, "statement_timeout_s": 600,
    "temp_file_limit_mb": 4096, "backup_retention_days": 14, "publish_layers": 200, "publish_daily_requests": 10_000_000,
    "map_badge": False, "maps": 200, "map_layers": 40, "map_charts": 40, "ows_projects": 0, "db_roles": 30,
    "team_members": 100, "basemap_api": False, "survey_projects": 0, "survey_max_points": 0, "gnss_external": False,
    "find_layer_credits": 1_000_000, "dedicated_geoserver": False, "raster_mb": 0, "clone_enabled": False,
    "snapshot_hours": 0, "price_toman": 0, "is_free": True, "is_public": False, "is_default": True,
    "is_renewable": True, "order": 1,
}


class Command(BaseCommand):
    help = "آماده‌سازی دستگاه pgpro. رمز مدیر PostgreSQL از PGPRO_PG_ADMIN_PASSWORD؛ رمز اولیه‌ی مدیر از PGPRO_ADMIN_PASSWORD."

    def handle(self, *args, **options):
        seed()
        self._site()
        self._plan()
        self._server()
        self._admin()
        self.stdout.write(self.style.SUCCESS("دستگاه آماده است."))

    def _site(self):
        conf = SiteSettings.get()
        conf.site_name = "pgpro"
        conf.tagline = "پایگاه داده مکانی PostGIS، روی دستگاه خودتان"
        conf.signup_open = False
        conf.allow_new_databases = True
        conf.max_databases_per_user = 50
        conf.sms_backend = "console"
        conf.assistant_enabled = False
        conf.pay_enabled = False
        conf.llm_partner_enabled = False
        conf.survey_enabled = False  # برداشت میدانی (GNSS) به HTTPS نیاز دارد؛ فاز ۲
        conf.map_tile_url = ""  # بدون نقشه‌ی پایه‌ی اینترنتی
        conf.save()

    def _plan(self):
        plan, _ = Plan.objects.update_or_create(slug=PLAN["slug"], defaults=PLAN)
        Plan.objects.exclude(pk=plan.pk).update(is_default=False, is_public=False)

    def _server(self):
        password = os.environ.get("PGPRO_PG_ADMIN_PASSWORD", "")
        if not password:
            self.stdout.write("PGPRO_PG_ADMIN_PASSWORD تنظیم نشده؛ ثبت سرور PostgreSQL رد شد.")
            return
        os.environ["PG_ADMIN_PASSWORD"] = password
        host = os.environ.get("PGPRO_PG_HOST", "127.0.0.1")
        public = f"{settings.DEVICE_NAME}.local"
        call_command("add_server", "pgpro-local", host=host, port=int(os.environ.get("PGPRO_PG_PORT", "5432")),
                     user=os.environ.get("PGPRO_PG_ADMIN_USER", "pgpro_admin"), public_host=public,
                     public_port=int(os.environ.get("PGPRO_PG_PUBLIC_PORT", "5432")), sslmode="prefer",
                     public_sslmode="prefer", default=True)
        DatabaseServer.objects.filter(name="pgpro-local").update(
            max_databases=500, notes="سرور PostgreSQL همین دستگاه (ساخته‌شده توسط device_init).")

    def _admin(self):
        if User.objects.filter(is_superuser=True).exists():
            return
        raw = os.environ.get("PGPRO_ADMIN_PASSWORD", services.DEFAULT_PASSWORD)
        services.create_user(services.DEFAULT_ADMIN, raw, full_name="مدیر دستگاه", admin=True, must_change=True)
        self.stdout.write(f"مدیر اولیه ساخته شد: {services.DEFAULT_ADMIN} (رمز باید در اولین ورود عوض شود).")
