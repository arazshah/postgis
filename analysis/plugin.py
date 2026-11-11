"""مانیفست پلاگین «تحلیل و پرسش فارسی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import home, jobs, nav, plugins
from kernel import profile as profile_sections
from kernel import settings as site_settings

plugin = plugins.register("analysis", "تحلیل و پرسش فارسی", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("ask", "پرسش فارسی", "analysis.jobs.do_ask", plugin=plugin.id,
                   destination="analysis:page", fragment="#history",
                   subject="analysis.jobs.ask_subject", notice="analysis.jobs.ask_notice")

nav.ws_section("share", "تحلیل", "analysis:page", "chart", "editor", plugin=plugin.id, order=10)

site_settings.section("llm_partner", "assistant", "راهنمای ساخت حساب مدل زبانی", plugin=plugin.id, order=150,
                      fields=("llm_partner_enabled", "llm_partner_name", "llm_partner_url"),
                      description="اگر کاربر در صفحه تحلیل حساب مدل زبانی ندارد، دکمه ساخت حساب با پیوند همکاری شما نشان داده می‌شود.")

profile_sections.section("ai", "مدل زبانی", "analysis/_profile_ai.html", plugin=plugin.id, order=10,
                         context="analysis.profile.context", badge="analysis.profile.has_key",
                         actions=("llm_save", "llm_delete"), handle="analysis.profile.handle", badge_title="کلید ثبت شده")

home.feed("analysis.home.feed", plugin=plugin.id, order=10)
home.step("analysis.home.step_llm", plugin=plugin.id, order=50)
