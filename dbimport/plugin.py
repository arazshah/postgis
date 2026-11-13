"""مانیفست پلاگین «ورود فایل»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import jobs, nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbimport", "ورود فایل", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/import/", "dbimport.views.import_start", "import", plugin=plugin.id, order=400)
routes.add("databases", "<int:pk>/import/<int:job_id>/", "dbimport.views.import_review", "import_review", plugin=plugin.id, order=410)

nav.ws_section("data", "ورود فایل", "databases:import", "upload", "editor", plugin=plugin.id, order=40, views=("databases:import", "databases:import_review"))
nav.home_action("data", "ورود فایل", "Shapefile، GeoPackage، GeoJSON، KML یا CSV را آپلود کن",
                "databases:import", "upload", plugin=plugin.id, order=30)
jobs.register_kind("import", "ورود فایل", "dbimport.jobs.do_import", plugin=plugin.id,
                   destination="databases:explore", done_title="دریافت و ورود فایل تمام شد")
jobs.register_tick("import_drafts", "dbimport.jobs.expire_import_drafts", plugin=plugin.id, order=45)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='فایل مکانی\u200cتان را در چند ثانیه به جدول PostGIS تبدیل کنید',
    category='data',
    featured=1,
    video='import',
    rail='ریل پایگاه ← داده ← ورود فایل',
    features=(
        'Shapefile، GeoPackage، GeoJSON، KML، CSV و DXF',
        'پیش\u200cنمایش جدول و سیستم مختصات پیش از ورود',
        'تشخیص خودکار نوع هندسه و رمزگذاری فارسی',
        'فایل\u200cهای بزرگ در پس\u200cزمینه وارد می\u200cشوند',
        'جایگزینی یا افزودن به جدول موجود',
    ),
    details='ورود فایل ساده\u200cترین راه آوردن داده\u200cی مکانی به پایگاه داده است: فایل را در مرورگر رها می\u200cکنید، سیستم هر لایه را می\u200cخواند، تعداد عارضه و نوع هندسه و چند سطر نمونه را نشان می\u200cدهد و با تأیید شما جدول را می\u200cسازد. نیازی به نصب QGIS یا نوشتن دستور ogr2ogr نیست.\n\nاگر مختصات فایل در سیستم دیگری باشد می\u200cتوانید هنگام ورود به WGS84 تبدیل کنید و برای فایل\u200cهای CSV ستون طول و عرض جغرافیایی را معرفی کنید. کارهای سنگین در پس\u200cزمینه اجرا می\u200cشوند و پایان آن را اعلان می\u200cگیرید.',
    audiences=(
        'student',
        'city',
        'survey',
        'org',
    ),
    steps=(
        ('فایل را رها کنید', 'Shapefile (به\u200cصورت zip)، GeoJSON، GeoPackage، KML، CSV یا DXF را انتخاب کنید.'),
        ('پیش\u200cنمایش را ببینید', 'نام جدول، سیستم مختصات و چند سطر نمونه را بررسی کنید.'),
        ('وارد کنید', 'با یک کلیک جدول ساخته می\u200cشود و در مرورگر داده روی نقشه دیده می\u200cشود.'),
    ),
    guides=(
        ('import', 'ورود فایل و سلامت داده'),
    ),
    kb=(
        ('import-formats', 'قالب\u200cهای قابل ورود'),
        ('import-shapefile-zip', 'ورود Shapefile فشرده'),
        ('import-csv-points', 'ورود نقطه از CSV'),
    ),
))
