"""مانیفست پلاگین «اعلان‌ها» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import plugins

plugin = plugins.register("notifications", "اعلان‌ها", kind="system", requires=("jobs",))
