"""مانیفست پلاگین «سایت و تنظیمات» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("core", "سایت و تنظیمات", kind="system")

nav.admin_item("customers", "core.contactrequest", None, plugin=plugin.id, order=70)
nav.admin_item("settings", "core.sitesettings", None, plugin=plugin.id, order=10)
nav.admin_item("settings", "core.teammember", None, plugin=plugin.id, order=20)
nav.admin_item("settings", "core.trustitem", None, plugin=plugin.id, order=30)
nav.admin_badge("core.contactrequest", "core.plugin.new_contacts", plugin=plugin.id)


def new_contacts() -> int:
    from .models import ContactRequest

    return ContactRequest.objects.filter(status=ContactRequest.Status.NEW).count()
