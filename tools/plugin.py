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
nav.home_action("share", "ابزارهای تحلیل مکانی", "بافر، نزدیک‌ترین، حوزه دسترسی و ... بدون کدنویسی",
                "tools:page", "toolbox", plugin=plugin.id, order=10)

jobs.register_kind("tool", "ابزار تحلیل", "tools.jobs.do_tool", plugin=plugin.id,
                   destination="tools:page", fragment="#history", subject="tools.jobs.subject")

sdk.category("proximity", "مجاورت و فاصله", "حریم، نزدیک‌ترین و فاصله‌ها", order=10)
sdk.category("aggregate", "شمارش و تراکم", "شمردن و خلاصه کردن نقطه‌ها", order=20)
sdk.category("overlay", "همپوشانی و تغییر", "برش دو لایه چندضلعی و مقایسه نسخه‌ها", order=30)
sdk.category("network", "شبکه معابر", "دسترسی روی خیابان‌ها", order=40)

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
    tagline='ابزار تحلیل مکانی با فرم؛ بدون یک خط SQL',
    category='analysis',
    video='analysis',
    featured=3,
    rail='ریل پایگاه ← تحلیل و انتشار ← ابزارها',
    features=(
        'بافر، برش، پاک\u200cکردن و همپوشانی',
        'نزدیک\u200cترین عارضه و شمارش در چندضلعی',
        'نقشه\u200cی تراکم و خوشه\u200cبندی شش\u200cضلعی',
        'حوزه\u200cی دسترسی و مسیر روی شبکه',
        'نتیجه جدول تازه در پایگاه شماست',
    ),
    details='هر ابزار یک فرم ساده است: لایه\u200cی ورودی، چند پارامتر و نام جدول نتیجه. خود سیستم SQL استاندارد را می\u200cسازد و اجرا می\u200cکند، در پس\u200cزمینه کار می\u200cکند و نتیجه را روی نقشه نشان می\u200cدهد.\n\nابزارها با آزمون طلایی قفل شده\u200cاند تا نتیجه\u200cی هر تحلیل قابل اتکا و تکرارپذیر باشد.',
    audiences=(
        'student',
        'city',
        'agri',
        'org',
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
