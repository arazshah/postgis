"""مانیفست پلاگین «تحلیل و پرسش فارسی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("analysis", "تحلیل و پرسش فارسی", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("ask", "پرسش فارسی", "analysis.jobs.do_ask", plugin=plugin.id,
                   destination="analysis:page", fragment="#history",
                   subject="analysis.jobs.ask_subject", notice="analysis.jobs.ask_notice")

nav.ws_section("share", "تحلیل", "analysis:page", "chart", "editor", plugin=plugin.id, order=10)
