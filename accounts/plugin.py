"""مانیفست پلاگین «حساب و ورود» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("accounts", "حساب و ورود", kind="system")

nav.admin_item("customers", "accounts.siteuser", None, plugin=plugin.id, order=10)
nav.admin_item("settings", "accounts.adminuser", None, plugin=plugin.id, order=40)
nav.admin_item("settings", "auth.group", None, plugin=plugin.id, order=50)
nav.admin_item("settings", "accounts.otpcode", None, plugin=plugin.id, order=60)
