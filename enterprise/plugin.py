"""مانیفست پلاگین «امکانات سازمانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("enterprise", "امکانات سازمانی", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("geoserver", "GeoServer اختصاصی", "enterprise.jobs.do_geoserver", plugin=plugin.id,
                   destination="enterprise:page")
jobs.register_kind("raster", "پردازش رستر", "enterprise.jobs.do_raster", plugin=plugin.id,
                   destination="enterprise:page")
jobs.register_kind("clone", "کپی پایگاه داده", "enterprise.jobs.do_clone", plugin=plugin.id,
                   destination="enterprise:page")

nav.ws_section("manage", "امکانات سازمانی", "enterprise:page", "server", "owner", plugin=plugin.id, order=40)
nav.admin_item("infra", "enterprise.geoserverinstance", None, plugin=plugin.id, order=40)
nav.admin_item("infra", "enterprise.raster", None, plugin=plugin.id, order=50)
jobs.register_tick("rasters_dir", "enterprise.jobs.tick_rasters_dir", plugin=plugin.id, order=5)
jobs.register_tick("snapshots", "enterprise.services.schedule_snapshots", plugin=plugin.id, order=70)
