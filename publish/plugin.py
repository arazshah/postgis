"""مانیفست پلاگین «انتشار نقشه و API» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import events, nav, plugins

plugin = plugins.register("publish", "انتشار نقشه و API", kind="feature", requires=("databases",))

nav.ws_section("share", "نقشه و API", "publish:manage", "globe", "editor", plugin=plugin.id, order=50, views=("publish:manage", "publish:map_builder"))
nav.ws_section("share", "WMS و WFS", "publish:ows", "cube", "editor", plugin=plugin.id, order=60, views=("publish:ows", "publish:ows_detail"))
nav.home_action("share", "انتشار نقشه و API", "لایه را با لینک عمومی، کاشی برداری یا API در وب بگذار",
                "publish:manage", "globe", plugin=plugin.id, order=20)
nav.admin_item("publish", "publish.service", None, plugin=plugin.id, order=10)
nav.admin_item("publish", "publish.apikey", None, plugin=plugin.id, order=20)
nav.admin_item("publish", "publish.dailyusage", None, plugin=plugin.id, order=30)
nav.admin_item("publish", "publish.owsproject", None, plugin=plugin.id, order=40)

events.listen(events.WORKSPACE_DELETED, "publish.events.workspace_deleted", plugin=plugin.id)
