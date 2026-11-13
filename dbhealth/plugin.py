"""مانیفست پلاگین «سلامت داده»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbhealth", "سلامت داده", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/explore/health/", "dbhealth.views.explore_health", "explore_health", plugin=plugin.id, order=320)

nav.ws_section("data", "سلامت داده", "databases:explore_health", "pulse", "viewer", plugin=plugin.id, order=70)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='مشکلات پنهان داده را پیدا و با یک کلیک اصلاح کنید',
    category='data',
    video='import',
    rail='ریل پایگاه ← داده ← سلامت داده',
    features=(
        'بررسی هندسه\u200cی نامعتبر، تهی و تکراری',
        'نبود نمایه\u200cی مکانی و آمار قدیمی جدول',
        'اصلاح خودکار همه\u200cی موارد با یک کلیک',
        'گزارش جدا برای هر جدول',
        'پیشگیری از خطای QGIS و انتشار نقشه',
    ),
    details='فایل\u200cهایی که از منابع مختلف می\u200cآیند اغلب هندسه\u200cی خراب یا نمایه\u200cی مکانی ندارند و همین باعث کندی نقشه یا خطای تحلیل می\u200cشود. سلامت داده همه\u200cی جدول\u200cها را می\u200cگردد، مشکل هر جدول را به زبان ساده می\u200cگوید و پیشنهاد اصلاح می\u200cدهد.\n\nاصلاح\u200cها امن هستند و فقط روی مورد اعلام\u200cشده اثر می\u200cگذارند؛ می\u200cتوانید یکی\u200cیکی یا یک\u200cجا اجرا کنید.',
    audiences=(
        'student',
        'city',
        'survey',
        'org',
    ),
    steps=(
        ('صفحه را باز کنید', 'در ریل پایگاه، بخش داده، «سلامت داده» را بزنید.'),
        ('گزارش را بخوانید', 'برای هر جدول مشکل\u200cها و میزان اهمیت\u200cشان نوشته شده است.'),
        ('اصلاح کنید', 'هر مورد یا «اصلاح خودکار همه» را بزنید.'),
    ),
    guides=(
        ('import', 'ورود فایل و سلامت داده'),
    ),
    kb=(
        ('data-health', 'سلامت داده چیست؟'),
        ('invalid-geometry-fix', 'رفع هندسه\u200cی نامعتبر'),
    ),
))
