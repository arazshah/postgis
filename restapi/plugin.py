"""مانیفست پلاگین «REST API و فرم میدانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import events, nav, plugins

plugin = plugins.register("restapi", "REST API و فرم میدانی", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "REST API و فرم میدانی", "restapi:manage", "braces", "editor", plugin=plugin.id, order=70)
events.listen(events.TABLE_DROPPED, "restapi.events.table_dropped", plugin=plugin.id, order=30)
events.listen(events.TABLE_RENAMED, "restapi.events.table_renamed", plugin=plugin.id, order=30)
events.listen(events.TABLE_USAGE, "restapi.events.table_usage", plugin=plugin.id, order=30)

