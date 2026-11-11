"""مانیفست پلاگین «تحلیل بازدید» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("analytics", "تحلیل بازدید", kind="system")

nav.admin_item("marketing", "analytics.sourcereport", None, plugin=plugin.id, order=10)
nav.admin_item("marketing", "analytics.trackedlink", None, plugin=plugin.id, order=20)
nav.admin_item("marketing", "analytics.visitor", None, plugin=plugin.id, order=30)
nav.admin_item("marketing", "analytics.visit", None, plugin=plugin.id, order=40)
nav.admin_item("marketing", "analytics.event", "رویدادهای بازدید", plugin=plugin.id, order=50)
nav.admin_quick("لینک ردیابی", "link", "admin:analytics_trackedlink_add", plugin=plugin.id, order=40)
