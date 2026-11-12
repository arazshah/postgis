"""مانیفست پلاگین «یافتن عارضه»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import jobs, nav, plugins, routes

plugin = plugins.register("dbfind", "یافتن عارضه", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/find/", "dbfind.views.find", "find", plugin=plugin.id, order=330)
routes.add("databases", "<int:pk>/find/columns/", "dbfind.views.find_columns", "find_columns", plugin=plugin.id, order=340)
routes.add("databases", "<int:pk>/find/values/", "dbfind.views.find_values", "find_values", plugin=plugin.id, order=350)
routes.add("databases", "<int:pk>/find/run/", "dbfind.views.find_run", "find_run", plugin=plugin.id, order=360)
routes.add("databases", "<int:pk>/find/save/", "dbfind.views.find_save", "find_save", plugin=plugin.id, order=370)
routes.add("databases", "<int:pk>/find/save/status/", "dbfind.views.find_save_status", "find_save_status", plugin=plugin.id, order=380)
routes.add("databases", "<int:pk>/find/sql/", "dbfind.views.find_sql", "find_sql", plugin=plugin.id, order=390)

nav.ws_section("data", "یافتن عارضه", "databases:find", "search", "viewer", plugin=plugin.id, order=20)
jobs.register_kind("find", "ذخیره‌ی نتیجه‌ی یافتن عارضه", "dbfind.jobs.do_find", plugin=plugin.id,
                   destination="databases:explore")
