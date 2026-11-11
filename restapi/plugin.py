"""مانیفست پلاگین «REST API و فرم میدانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("restapi", "REST API و فرم میدانی", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "REST API و فرم میدانی", "restapi:manage", "braces", "editor", plugin=plugin.id, order=70)
