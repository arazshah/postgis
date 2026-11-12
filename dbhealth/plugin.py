"""مانیفست پلاگین «سلامت داده»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes

plugin = plugins.register("dbhealth", "سلامت داده", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/explore/health/", "dbhealth.views.explore_health", "explore_health", plugin=plugin.id, order=320)

nav.ws_section("data", "سلامت داده", "databases:explore_health", "pulse", "viewer", plugin=plugin.id, order=70)
