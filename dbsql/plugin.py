"""مانیفست پلاگین «اجرای SQL»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes

plugin = plugins.register("dbsql", "اجرای SQL", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/explore/sql/", "dbsql.views.explore_sql", "explore_sql", plugin=plugin.id, order=190)
routes.add("databases", "<int:pk>/explore/sql/ask/", "dbsql.views.explore_sql_ask", "explore_sql_ask", plugin=plugin.id, order=200)
routes.add("databases", "<int:pk>/explore/sql/why/", "dbsql.views.explore_sql_why", "explore_sql_why", plugin=plugin.id, order=210)

nav.ws_section("data", "اجرای SQL", "databases:explore_sql", "code", "viewer", plugin=plugin.id, order=30)
nav.home_action("data", "اجرای SQL", "کوئری بنویس و نتیجه را همان‌جا ببین (به‌طور پیش‌فرض فقط‌خواندنی)",
                "databases:explore_sql", "code", plugin=plugin.id, order=20)
