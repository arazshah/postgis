"""مانیفست پلاگین «دستیار هوشمند» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("assistant", "دستیار هوشمند", kind="system", requires=("kb",))

nav.admin_item("support", "assistant.usage", None, plugin=plugin.id, order=60)
