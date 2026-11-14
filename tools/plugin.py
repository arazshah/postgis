"""مانیفست پلاگین «ابزارهای تحلیل» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
import pkgutil
from importlib import import_module

from kernel import home, jobs, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

from . import plugins as builtin
from . import sdk

plugin = plugins.register("tools", "ابزارهای تحلیل", kind="feature", requires=("analysis",))

nav.ws_section("share", "ابزارها", "tools:page", "toolbox", "editor", plugin=plugin.id, order=20, views=("tools:page", "tools:detail"))
nav.home_action("share", "جعبه‌ابزار تحلیل مکانی", "۵۰ ابزار آماده از حریم و مساحت تا آمار مکانی و شبکه، بدون کدنویسی",
                "tools:page", "toolbox", plugin=plugin.id, order=10)

jobs.register_kind("tool", "ابزار تحلیل", "tools.jobs.do_tool", plugin=plugin.id,
                   destination="tools:page", fragment="#history", subject="tools.jobs.subject")

sdk.category("proximity", "مجاورت و فاصله", "حریم، نزدیک‌ترین‌ها و ارتباط عارضه‌ها با هم", order=10, icon="c-proximity")
sdk.category("overlay", "همپوشانی و ترکیب لایه‌ها", "برش، اشتراک، اجتماع، پیوند مکانی و مقایسه نسخه‌ها", order=20, icon="c-overlay")
sdk.category("geometry", "هندسه و تبدیل", "مرکز، پوسته، یکپارچه‌سازی، ساده‌سازی و تبدیل نوع عارضه", order=30, icon="c-geometry")
sdk.category("measure", "اندازه‌گیری", "طول، مساحت، مختصات و شاخص‌های شکل", order=40, icon="c-measure")
sdk.category("linear", "خط و ارجاع خطی", "نقطه‌گذاری و تقسیم خط‌ها، تقاطع و سرانجام‌ها", order=50, icon="c-linear")
sdk.category("aggregate", "شمارش، تراکم و شبکه‌بندی", "شمردن، خلاصه کردن و ساخت شبکه‌های منظم", order=60, icon="c-density")
sdk.category("stats", "آمار مکانی", "مرکز میانگین، کانون‌های داغ و خوشه‌بندی آماری", order=70, icon="c-stats")
sdk.category("quality", "کیفیت و پاک‌سازی داده", "اصلاح هندسه، حذف تکراری‌ها و یافتن مشکل‌ها", order=80, icon="c-quality")
sdk.category("network", "شبکه معابر", "دسترسی، مسیر و فاصله روی خیابان‌ها", order=90, icon="c-network")

# ابزارهای داخلی: هر ماژول tools/plugins/<نام>.py (بدون زیرخط آغازین) خودکار بار و ثبت می‌شود
for _m in pkgutil.iter_modules(builtin.__path__):
    if not _m.name.startswith("_"):
        import_module(f"{builtin.__name__}.{_m.name}")

# ابزار از اپ‌های دیگر: هر اپ نصب‌شده می‌تواند ماژول `geotools` داشته باشد
from django.utils.module_loading import autodiscover_modules  # noqa: E402

autodiscover_modules("geotools")

home.feed("tools.home.feed", plugin=plugin.id, order=20)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='جعبه‌ابزار ۵۰ تایی تحلیل مکانی؛ بدون یک خط SQL',
    category='analysis',
    video='analysis',
    featured=3,
    rail='ریل پایگاه ← تحلیل و انتشار ← ابزارها',
    features=(
        'بافر، برش، اشتراک، اجتماع و پیوند مکانی',
        'اندازه‌گیری، مختصات و شاخص‌های شکل',
        'تراکم، شبکه‌ی مربعی و خوشه‌بندی',
        'آمار مکانی: کانون داغ، بیضی و K-Means',
        'اصلاح هندسه و پاک‌سازی داده',
        'حوزه‌ی دسترسی و ماتریس مبدأ–مقصد روی شبکه',
    ),
    details='جعبه\u200cابزار ۵۰ ابزار در ۹ دسته دارد و هر ابزار یک فرم ساده است: لایه\u200cی ورودی، چند پارامتر و نام جدول نتیجه. خود سیستم SQL استاندارد را می\u200cسازد و اجرا می\u200cکند، در پس\u200cزمینه کار می\u200cکند و نتیجه را روی نقشه نشان می\u200cدهد.\n\nابزارها با آزمون طلایی قفل شده\u200cاند تا نتیجه\u200cی هر تحلیل قابل اتکا و تکرارپذیر باشد.',
    audiences=(
        'student',
        'city',
        'agri',
    ),
    steps=(
        ('ابزار را انتخاب کنید', 'مثلاً «حریم (بافر)».'),
        ('پارامتر بدهید', 'لایه، فاصله و نام نتیجه.'),
        ('اجرا و مشاهده', 'نتیجه روی نقشه و در جدول جدید.'),
    ),
    guides=(
        ('analysis', 'تحلیل بدون SQL'),
    ),
    kb=(
        ('analysis-tools', 'ابزارهای تحلیل'),
        ('tools-proximity', 'نزدیکی و بافر'),
        ('tools-overlay', 'همپوشانی'),
        ('tools-density', 'تراکم'),
    ),
))
