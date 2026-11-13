"""مانیفست پلاگین «یافتن عارضه»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import jobs, nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbfind", "یافتن عارضه", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/find/", "dbfind.views.find", "find", plugin=plugin.id, order=330)
routes.add("databases", "<int:pk>/find/columns/", "dbfind.views.find_columns", "find_columns", plugin=plugin.id, order=340)
routes.add("databases", "<int:pk>/find/values/", "dbfind.views.find_values", "find_values", plugin=plugin.id, order=350)
routes.add("databases", "<int:pk>/find/run/", "dbfind.views.find_run", "find_run", plugin=plugin.id, order=360)
routes.add("databases", "<int:pk>/find/save/", "dbfind.views.find_save", "find_save", plugin=plugin.id, order=370)
routes.add("databases", "<int:pk>/find/save/status/", "dbfind.views.find_save_status", "find_save_status", plugin=plugin.id, order=380)
routes.add("databases", "<int:pk>/find/sql/", "dbfind.views.find_sql", "find_sql", plugin=plugin.id, order=390)

nav.ws_section("data", "یافتن عارضه", "databases:find", "search", "viewer", plugin=plugin.id, order=20)
jobs.register_kind("find", "ذخیره‌ی نتیجه‌ی یافتن عارضه", "dbfind.jobs.do_find", plugin=plugin.id,
                   destination="databases:explore")

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='عارضه را با ویژگی و جایش پیدا کنید',
    category='analysis',
    video='find',
    rail='ریل پایگاه ← داده ← یافتن عارضه',
    features=(
        'شرط روی ویژگی\u200cها مثل نوع = بیمارستان',
        'شرط مکانی: داخل محله، تا فاصله\u200cی مشخص',
        'جست\u200cوجو داخل شکلی که روی نقشه می\u200cکشید',
        'نتیجه روی نقشه برجسته می\u200cشود',
        'ترکیب چند شرط بدون SQL',
    ),
    details='اگر بپرسید «کدام مدرسه\u200cها تا ۵۰۰ متری یک ایستگاه مترو هستند؟» یافتن عارضه همان را با فرم ساده پاسخ می\u200cدهد. شرط\u200cهای ویژگی و مکان را ترکیب می\u200cکنید و نتیجه هم در جدول و هم روی نقشه نمایش داده می\u200cشود.\n\nبرای کسانی که SQL نمی\u200cدانند، سریع\u200cترین راه رسیدن به جواب مکانی است.',
    audiences=(
        'student',
        'city',
        'agri',
        'org',
    ),
    steps=(
        ('لایه را انتخاب کنید', 'جدول مورد جست\u200cوجو را برگزینید.'),
        ('شرط بدهید', 'ویژگی، فاصله یا محدوده\u200cی کشیده\u200cشده.'),
        ('نتیجه را ببینید', 'عارضه\u200cهای پیداشده روی نقشه برجسته می\u200cشوند.'),
    ),
    guides=(
        ('find', 'یافتن عارضه'),
    ),
    kb=(
        ('find-features', 'یافتن عارضه با ویژگی و مکان'),
        ('find-table', 'پیدا کردن جدول'),
    ),
))
