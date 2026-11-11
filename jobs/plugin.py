"""مانیفست پلاگین «کارهای پس‌زمینه و بکاپ» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("jobs", "کارهای پس‌زمینه و بکاپ", kind="system")

jobs.register_kind("backup", "بکاپ", "jobs.services._do_backup", plugin=plugin.id,
                   destination="databases:backups", quiet_when_auto=True)
jobs.register_kind("restore", "بازگردانی", "jobs.services._do_restore", plugin=plugin.id,
                   destination="databases:backups")
jobs.register_kind("restore_test", "آزمون بازگردانی", "jobs.services._do_restore_test", plugin=plugin.id,
                   destination="databases:backups", quiet_when_auto=True)
jobs.register_kind("import", "ورود فایل", "jobs.services._do_import", plugin=plugin.id,
                   destination="databases:explore", done_title="دریافت و ورود فایل تمام شد")

nav.admin_item("infra", "jobs.job", None, plugin=plugin.id, order=30)
jobs.register_tick("nightly", "jobs.services.schedule_nightly", plugin=plugin.id, order=20)
jobs.register_tick("restore_test", "jobs.services.schedule_restore_test", plugin=plugin.id, order=30)
jobs.register_tick("cleanup", "jobs.services.cleanup", plugin=plugin.id, order=40)
jobs.register_tick("alerts", "jobs.services._tick_alerts", plugin=plugin.id, order=50)
