"""مانیفست پلاگین «تصویر ماهواره‌ای» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("satellite", "تصویر ماهواره‌ای", kind="feature", requires=("databases", "enterprise", "jobs"))

jobs.register_kind("satellite", "دریافت تصویر ماهواره‌ای", "satellite.jobs.do_satellite", plugin=plugin.id,
                   destination="satellite:index")
jobs.register_kind("sat_analysis", "تحلیل ماهواره‌ای", "satellite.jobs.do_sat_analysis", plugin=plugin.id,
                   destination="satellite:index")

nav.ws_section("data", "تصویر ماهواره‌ای", "satellite:index", "satellite", "viewer", plugin=plugin.id, order=60)
jobs.register_tick("satellite", "satellite.services.poll", plugin=plugin.id, order=80)
jobs.register_tick("monitors", "satellite.monitor_service.run_due", plugin=plugin.id, order=90)
