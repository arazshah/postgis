"""مانیفست پلاگین «تیم و کاربران»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes

plugin = plugins.register("dbteam", "تیم و کاربران", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/team/", "dbteam.views.team_page", "team", plugin=plugin.id, order=80)

nav.ws_section("manage", "تیم و کاربران", "databases:team", "users", "owner", plugin=plugin.id, order=10)
nav.home_action("manage", "تیم و دسترسی", "همکارانت را با نقش مشاهده‌گر یا ویرایشگر دعوت کن",
                "databases:team", "users", plugin=plugin.id, order=30)
