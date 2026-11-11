"""مانیفست پلاگین «داده آماده و نقشه پایه ایران» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("iranmap", "داده آماده و نقشه پایه ایران", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("basemap", "ساخت نقشه پایه ایران", "iranmap.tasks.do_basemap", plugin=plugin.id,
                   destination="iranmap:ready", quiet_when_auto=True)
jobs.register_kind("osm_refresh", "به‌روزرسانی داده OSM ایران", "iranmap.tasks.do_osm_refresh", plugin=plugin.id,
                   destination="iranmap:ready", quiet_when_auto=True,
                   done_title="دریافت داده آماده ایران تمام شد")
jobs.register_kind("osm_import", "داده آماده ایران", "iranmap.tasks.do_osm_import", plugin=plugin.id,
                   destination="iranmap:ready", done_title="دریافت داده آماده ایران تمام شد")

nav.ws_section("data", "داده آماده ایران", "iranmap:ready", "pin", "editor", plugin=plugin.id, order=50)
nav.admin_item("infra", "iranmap.area", None, plugin=plugin.id, order=60)
jobs.register_tick("map_data", "iranmap.tasks.schedule", plugin=plugin.id, order=60)
