"""مانیفست پلاگین «تحلیل و پرسش فارسی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins

plugin = plugins.register("analysis", "تحلیل و پرسش فارسی", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("ask", "پرسش فارسی", "analysis.jobs.do_ask", plugin=plugin.id,
                   destination="analysis:page", fragment="#history",
                   subject="analysis.jobs.ask_subject", notice="analysis.jobs.ask_notice")
jobs.register_kind("tool", "ابزار تحلیل", "analysis.jobs.do_tool", plugin=plugin.id,
                   destination="tools:page", fragment="#history",
                   subject="analysis.jobs.tool_subject")

nav.ws_section("share", "تحلیل", "analysis:page", "chart", "editor", plugin=plugin.id, order=10)
