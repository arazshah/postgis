"""مانیفست پلاگین «ابزارهای تحلیل» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("tools", "ابزارهای تحلیل", kind="feature", requires=("analysis",))

nav.ws_section("share", "ابزارها", "tools:page", "toolbox", "editor", plugin=plugin.id, order=20, views=("tools:page", "tools:detail"))
nav.home_action("share", "ابزارهای تحلیل مکانی", "بافر، نزدیک‌ترین، حوزه دسترسی و ... بدون کدنویسی",
                "tools:page", "toolbox", plugin=plugin.id, order=10)
