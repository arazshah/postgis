"""مانیفست پلاگین «کلاس درس» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins
from kernel import settings as site_settings

plugin = plugins.register("classroom", "کلاس درس", kind="feature", requires=("databases", "maps"))

nav.admin_item("customers", "classroom.classroom", None, plugin=plugin.id, order=40)
nav.admin_item("customers", "classroom.contract", None, plugin=plugin.id, order=50)
nav.admin_item("customers", "classroom.contractrequest", None, plugin=plugin.id, order=60)
jobs.register_tick("classes", "classroom.services.tick", plugin=plugin.id, order=10)

site_settings.section("class_plan", "users", "پلن کلاس و دانشگاه", plugin=plugin.id, order=170,
                      fields=("class_price_per_student",))
