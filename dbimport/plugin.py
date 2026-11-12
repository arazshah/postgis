"""مانیفست پلاگین «ورود فایل»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import jobs, nav, plugins, routes

plugin = plugins.register("dbimport", "ورود فایل", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/import/", "dbimport.views.import_start", "import", plugin=plugin.id, order=400)
routes.add("databases", "<int:pk>/import/<int:job_id>/", "dbimport.views.import_review", "import_review", plugin=plugin.id, order=410)

nav.ws_section("data", "ورود فایل", "databases:import", "upload", "editor", plugin=plugin.id, order=40, views=("databases:import", "databases:import_review"))
nav.home_action("data", "ورود فایل", "Shapefile، GeoPackage، GeoJSON، KML یا CSV را آپلود کن",
                "databases:import", "upload", plugin=plugin.id, order=30)
jobs.register_kind("import", "ورود فایل", "dbimport.jobs.do_import", plugin=plugin.id,
                   destination="databases:explore", done_title="دریافت و ورود فایل تمام شد")
jobs.register_tick("import_drafts", "dbimport.jobs.expire_import_drafts", plugin=plugin.id, order=45)
