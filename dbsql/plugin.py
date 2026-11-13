"""مانیفست پلاگین «اجرای SQL»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbsql", "اجرای SQL", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/explore/sql/", "dbsql.views.explore_sql", "explore_sql", plugin=plugin.id, order=190)
routes.add("databases", "<int:pk>/explore/sql/ask/", "dbsql.views.explore_sql_ask", "explore_sql_ask", plugin=plugin.id, order=200)
routes.add("databases", "<int:pk>/explore/sql/why/", "dbsql.views.explore_sql_why", "explore_sql_why", plugin=plugin.id, order=210)

nav.ws_section("data", "اجرای SQL", "databases:explore_sql", "code", "viewer", plugin=plugin.id, order=30)
nav.home_action("data", "اجرای SQL", "کوئری بنویس و نتیجه را همان‌جا ببین (به‌طور پیش‌فرض فقط‌خواندنی)",
                "databases:explore_sql", "code", plugin=plugin.id, order=20)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='SQL مکانی را در مرورگر بنویسید و نتیجه را همان\u200cجا ببینید',
    category='analysis',
    video='sql',
    rail='ریل پایگاه ← داده ← اجرای SQL',
    features=(
        'اجرای مستقیم SQL و PostGIS در مرورگر',
        'نتیجه به\u200cصورت جدول و روی نقشه',
        'ساخت جدول جدید از نتیجه با یک تیک',
        'سقف زمان و حجم برای امنیت پایگاه',
        'نمونه\u200cکوئری\u200cهای آماده\u200cی بافر و نزدیک\u200cترین',
    ),
    details='کنسول SQL برای کسانی است که تحلیل را با کد می\u200cنویسند اما نمی\u200cخواهند ابزار جدا نصب کنند. کوئری را بنویسید، اجرا کنید و نتیجه را جدول یا نقشه ببینید؛ نتیجه را می\u200cتوانید با یک تیک به جدول تازه تبدیل کنید.\n\nنمونه\u200cکوئری\u200cهای آماده (بافر، نزدیک\u200cترین عارضه، تقاطع، شمارش نقطه در چندضلعی) شروع را سریع می\u200cکنند.',
    audiences=(
        'student',
        'dev',
        'org',
    ),
    steps=(
        ('کوئری بنویسید', 'یک نمونه را انتخاب یا کوئری خودتان را وارد کنید.'),
        ('اجرا کنید', 'نتیجه جدول و در صورت وجود هندسه روی نقشه دیده می\u200cشود.'),
        ('ذخیره کنید', 'با گزینه\u200cی ساخت جدول، نتیجه در پایگاه می\u200cماند.'),
    ),
    guides=(
        ('sql', 'اجرای SQL و تحلیل مکانی'),
    ),
    kb=(
        ('sql-console', 'کنسول SQL'),
        ('sql-buffer', 'بافر با SQL'),
        ('sql-nearest-features', 'نزدیک\u200cترین عارضه\u200cها'),
    ),
))
