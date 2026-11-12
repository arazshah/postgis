"""مانیفست پلاگین «بکاپ و بازگردانی»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes

plugin = plugins.register("dbbackup", "بکاپ و بازگردانی", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/backups/", "dbbackup.views.backups", "backups", plugin=plugin.id, order=100)
routes.add("databases", "<int:pk>/backups/new/", "dbbackup.views.backup_new", "backup_new", plugin=plugin.id, order=110)
routes.add("databases", "<int:pk>/backups/<int:job_id>/download/", "dbbackup.views.backup_download", "backup_download", plugin=plugin.id, order=120)
routes.add("databases", "<int:pk>/backups/<int:job_id>/restore/", "dbbackup.views.backup_restore", "backup_restore", plugin=plugin.id, order=130)

nav.ws_section("manage", "بکاپ و بازگردانی", "databases:backups", "clock", "owner", plugin=plugin.id, order=20)
nav.home_action("manage", "بکاپ‌ها", "نسخه پشتیبان بگیر، دانلود کن یا بازگردانی کن",
                "databases:backups", "clock", plugin=plugin.id, order=10)
