"""مانیفست پلاگین «تحلیل و پرسش فارسی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import home, jobs, llm, nav, plugins
from kernel import profile as profile_sections
from kernel import settings as site_settings
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

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

from .llm_config import AnalysisLlm  # noqa: E402

llm.set_provider(AnalysisLlm())
admin_dash.report_sheet("analysis.reports.sheets", plugin=plugin.id, order=10)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='سؤالتان را فارسی بنویسید؛ تحلیل مکانی انجام می\u200cشود',
    category='analysis',
    video='analysis',
    featured=2,
    rail='ریل پایگاه ← تحلیل و انتشار ← تحلیل',
    features=(
        'پرسش فارسی با s3geo',
        'نقشه و نمودار از نتیجه\u200cی تحلیل',
        'اجرای کار در پس\u200cزمینه با اعلان',
        'تاریخچه\u200cی اجراها',
        'پایه\u200cی ابزارهای تحلیل پایگاه',
    ),
    details='«تعداد مدرسه\u200cهای هر منطقه را بشمار» را همان\u200cطور که می\u200cگویید بنویسید؛ سیستم کوئری مکانی مناسب را می\u200cسازد، اجرا می\u200cکند و نتیجه را جدول و نقشه نشان می\u200cدهد. کلید مدل زبانی را خودتان می\u200cدهید و رمزنگاری می\u200cشود.\n\nاجراهای قبلی در تاریخچه می\u200cمانند تا دوباره باز یا نتیجه به نقشه تبدیل شود.',
    audiences=(
        'student',
        'city',
        'org',
    ),
    steps=(
        ('سؤال بنویسید', 'فارسی و ساده.'),
        ('نتیجه را ببینید', 'جدول و نقشه.'),
        ('نقشه یا نمودار بسازید', 'نتیجه را به نقشه\u200cی چندلایه ببرید.'),
    ),
    guides=(
        ('analysis', 'تحلیل بدون SQL و پرسش فارسی'),
    ),
    kb=(
        ('ask-in-persian', 'پرسش فارسی'),
        ('map-chart-from-analysis', 'نقشه و نمودار از تحلیل'),
    ),
))
