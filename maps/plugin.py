"""مانیفست پلاگین «نقشه‌های چندلایه» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("maps", "نقشه‌های چندلایه", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "نقشه‌های چندلایه", "maps:index", "layers", "viewer", plugin=plugin.id, order=40, views=("maps:index", "maps:composer", "maps:quick"))
nav.home_action("share", "نقشه‌های چندلایه", "چند لایه را با سبک دلخواه یک‌جا بچین و ارائه بده",
                "maps:index", "layers", plugin=plugin.id, order=30)
nav.admin_item("publish", "maps.webmap", None, plugin=plugin.id, order=50)
