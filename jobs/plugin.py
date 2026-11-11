"""مانیفست پلاگین «کارهای پس‌زمینه و بکاپ» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import admin as admin_dash
from kernel import jobs, nav, plugins
from kernel import settings as site_settings

plugin = plugins.register("jobs", "کارهای پس‌زمینه و بکاپ", kind="system")

jobs.register_kind("backup", "بکاپ", "jobs.services._do_backup", plugin=plugin.id,
                   destination="databases:backups", quiet_when_auto=True)
jobs.register_kind("restore", "بازگردانی", "jobs.services._do_restore", plugin=plugin.id,
                   destination="databases:backups")
jobs.register_kind("restore_test", "آزمون بازگردانی", "jobs.services._do_restore_test", plugin=plugin.id,
                   destination="databases:backups", quiet_when_auto=True)

nav.admin_item("infra", "jobs.job", None, plugin=plugin.id, order=30)
jobs.register_tick("nightly", "jobs.services.schedule_nightly", plugin=plugin.id, order=20)
jobs.register_tick("restore_test", "jobs.services.schedule_restore_test", plugin=plugin.id, order=30)
jobs.register_tick("cleanup", "jobs.services.cleanup", plugin=plugin.id, order=40)
jobs.register_tick("alerts", "jobs.services._tick_alerts", plugin=plugin.id, order=50)

site_settings.tab("backup", "بکاپ خارج از سرور", "db", plugin=plugin.id, order=80, status="jobs.settings_admin.tab_status")
site_settings.section("offsite", "backup", "بکاپ خارج از سرور (فضای ابری)", plugin=plugin.id, order=80,
                      fields=("offsite_status", "offsite_enabled", "offsite_endpoint", "offsite_bucket", "offsite_region", "offsite_prefix", "offsite_access_key", "offsite_secret_key", "clear_offsite_keys", "offsite_encrypt", "offsite_tools"),
                      description="بعد از هر بکاپ موفق، نسخه‌ی دومی در باکت S3 (مثلاً پارس‌پک) ذخیره می‌شود. مدت نگهداری در باکت همان مدت نگهداری بکاپ در پلن است. ابتدا ذخیره کنید، سپس «آزمایش اتصال» را بزنید. کلیدها رمزنگاری‌شده ذخیره می‌شوند و هرگز دوباره نمایش داده نمی‌شوند.")
site_settings.display("offsite_status", "وضعیت بکاپ ابری", "jobs.settings_admin.offsite_status", plugin=plugin.id)
site_settings.display("offsite_tools", "ابزار فضای ابری", "jobs.settings_admin.offsite_tools", plugin=plugin.id)
site_settings.tool("offsitetest", "offsite-test/", "jobs.settings_admin.offsite_test_view", plugin=plugin.id)

admin_dash.attention("jobs.admin_cards.attention", plugin=plugin.id, order=50)
admin_dash.attention("jobs.admin_cards.attention_offsite", plugin=plugin.id, order=70)
admin_dash.health("jobs.admin_cards.health", plugin=plugin.id, order=20)
