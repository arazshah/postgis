"""مانیفست پلاگین «نقشه‌های چندلایه» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import events, home, nav, plugins

plugin = plugins.register("maps", "نقشه‌های چندلایه", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "نقشه‌های چندلایه", "maps:index", "layers", "viewer", plugin=plugin.id, order=40, views=("maps:index", "maps:composer", "maps:quick"))
nav.home_action("share", "نقشه‌های چندلایه", "چند لایه را با سبک دلخواه یک‌جا بچین و ارائه بده",
                "maps:index", "layers", plugin=plugin.id, order=30)
nav.admin_item("publish", "maps.webmap", None, plugin=plugin.id, order=50)

home.feed("maps.home.feed", plugin=plugin.id, order=30)
home.step("maps.home.step_map", plugin=plugin.id, order=40)
events.listen(events.TABLE_DROPPED, "maps.events.table_dropped", plugin=plugin.id, order=10)
events.listen(events.TABLE_RENAMED, "maps.events.table_renamed", plugin=plugin.id, order=10)
events.listen(events.TABLE_USAGE, "maps.events.table_usage", plugin=plugin.id, order=10)
events.listen(events.TABLE_MAP_TARGETS, "maps.events.table_map_targets", plugin=plugin.id, order=10)

