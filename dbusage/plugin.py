"""مانیفست پلاگین «مصرف و کارایی»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes

plugin = plugins.register("dbusage", "مصرف و کارایی", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/usage/", "dbusage.views.usage_page", "usage", plugin=plugin.id, order=90)

nav.ws_section("manage", "مصرف و کارایی", "databases:usage", "gauge", "owner", plugin=plugin.id, order=30)
nav.home_action("manage", "مصرف و کارایی", "نمودار حجم و درخواست‌ها و پیشنهاد نمایه",
                "databases:usage", "gauge", plugin=plugin.id, order=20)
