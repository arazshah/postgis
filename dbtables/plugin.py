"""مانیفست پلاگین «جدول‌ها و ویرایش داده»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbtables", "جدول‌ها و ویرایش داده", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/explore/", "dbtables.views.explore", "explore", plugin=plugin.id, order=140)
routes.add("databases", "<int:pk>/explore/new/", "dbtables.views.table_new", "table_new", plugin=plugin.id, order=150)
routes.add("databases", "<int:pk>/explore/new/preview/", "dbtables.views.table_preview", "table_preview", plugin=plugin.id, order=160)
routes.add("databases", "<int:pk>/explore/new/srid/", "dbtables.views.table_srid", "table_srid", plugin=plugin.id, order=170)
routes.add("databases", "<int:pk>/explore/tables.json", "dbtables.views.tables_json", "tables_json", plugin=plugin.id, order=180)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/", "dbtables.views.explore_table", "explore_table", plugin=plugin.id, order=220)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/structure/", "dbtables.views.table_structure", "table_structure", plugin=plugin.id, order=230)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/drop/", "dbtables.views.explore_drop", "explore_drop", plugin=plugin.id, order=240)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/edit/mode/", "dbtables.views.explore_edit_mode", "explore_edit_mode", plugin=plugin.id, order=250)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/edit/row/", "dbtables.views.explore_edit_row", "explore_edit_row", plugin=plugin.id, order=260)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/edit/apply/", "dbtables.views.explore_edit_apply", "explore_edit_apply", plugin=plugin.id, order=270)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/edit/undo/", "dbtables.views.explore_edit_undo", "explore_edit_undo", plugin=plugin.id, order=280)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/geojson/", "dbtables.views.explore_geojson", "explore_geojson", plugin=plugin.id, order=290)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/csv/", "dbtables.views.explore_csv", "explore_csv", plugin=plugin.id, order=300)
routes.add("databases", "<int:pk>/explore/t/<str:schema>/<str:table>/export/<str:fmt>/", "dbtables.views.explore_export", "explore_export", plugin=plugin.id, order=310)

nav.ws_section("data", "جدول‌ها", "databases:explore", "table", "viewer", plugin=plugin.id, order=10, views=("databases:explore", "databases:explore_table"))
nav.home_action("data", "جدول‌ها و داده‌ها", "جدول‌ها، ستون‌ها و روی نقشه را ببین؛ خروجی CSV و GeoJSON بگیر",
                "databases:explore", "table", plugin=plugin.id, order=10)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='جدول\u200cها را ببینید، روی نقشه بیاورید و با امنیت ویرایش کنید',
    category='data',
    video='edittable',
    rail='ریل پایگاه ← داده ← جدول\u200cها',
    features=(
        'مرورگر جدول و نقشه بدون نصب نرم\u200cافزار',
        'ویرایش سطر و هندسه با پیش\u200cنویس و تأیید',
        'بازگرداندن آخرین ذخیره',
        'تغییر ساختار جدول: ستون، نام و حذف',
        'خروجی در هفت قالب',
    ),
    details='مرورگر داده همه\u200cی جدول\u200cهای پایگاه را نشان می\u200cدهد؛ هر لایه را روی نقشه ببینید و خروجی بگیرید. ویرایش عمداً دو مرحله\u200cای است: تغییرها ابتدا پیش\u200cنویس هستند، بازبینی می\u200cشوند و بعد یک\u200cجا ذخیره می\u200cشوند و در صورت نیاز آخرین ذخیره برگردانده می\u200cشود.\n\nساختار جدول (ستون تازه، تغییر نام، حذف) هم از همین\u200cجا و با هشدار پیش از کار خطرناک قابل تغییر است.',
    audiences=(
        'student',
        'city',
        'org',
        'dev',
    ),
    steps=(
        ('جدول را باز کنید', 'از فهرست جدول\u200cها یکی را انتخاب کنید و روی نقشه ببینید.'),
        ('حالت ویرایش را روشن کنید', 'سطر یا هندسه را اضافه، ویرایش یا حذف کنید.'),
        ('بازبینی و ذخیره', 'تغییرها را مرور و یک\u200cجا ذخیره کنید.'),
    ),
    guides=(
        ('explore', 'مرورگر داده'),
        ('edittable', 'ویرایش داده و شکل جدول'),
    ),
    kb=(
        ('explorer-overview', 'مرورگر داده'),
        ('edit-table-data', 'ویرایش داده'),
        ('export-formats', 'قالب\u200cهای خروجی'),
    ),
))
