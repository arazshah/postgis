"""مانیفست پلاگین «نقشه‌های چندلایه» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import events, home, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("maps", "نقشه‌های چندلایه", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "نقشه‌های چندلایه", "maps:index", "layers", "viewer", plugin=plugin.id, order=40, views=("maps:index", "maps:composer", "maps:quick"))
nav.home_action("share", "نقشه‌های چندلایه", "چند لایه را با سبک دلخواه یک‌جا بچین و ارائه بده",
                "maps:index", "layers", plugin=plugin.id, order=30)
nav.admin_item("publish", "maps.webmap", None, plugin=plugin.id, order=50)

home.feed("maps.home.feed", plugin=plugin.id, order=30)
home.step("maps.home.step_map", plugin=plugin.id, order=40)
events.listen(events.TABLE_DROPPED, "maps.events.table_dropped", plugin=plugin.id, order=10)
events.listen(events.TABLE_RENAMED, "maps.events.table_renamed", plugin=plugin.id, order=10)
events.listen(events.TABLE_USAGE, "maps.events.table_usage", plugin=plugin.id, order=10)
events.listen(events.TABLE_MAP_TARGETS, "maps.events.table_map_targets", plugin=plugin.id, order=10)
admin_dash.report_sheet("maps.reports.sheets", plugin=plugin.id, order=20)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='چند لایه را روی یک نقشه بیاورید و با لینک منتشر کنید',
    category='publish',
    video='maps',
    featured=4,
    rail='ریل پایگاه ← تحلیل و انتشار ← نقشه\u200cهای چندلایه',
    features=(
        'استودیوی نقشه با رنگ و سبک هر لایه',
        'نمودار روی نقشه: میله\u200cای، هیستوگرام، سری زمانی',
        'اسلاید و ارائه از نقشه',
        'چاپ PDF و PNG با اندازه\u200cی دلخواه',
        'مقایسه با پرده\u200cی کشویی',
        'لینک عمومی، iframe و پروژه\u200cی QGIS',
    ),
    details='استودیوی نقشه جایی است که جدول\u200cهای مکانی به محصول قابل ارائه تبدیل می\u200cشوند: لایه\u200cها را کنار هم می\u200cگذارید، رنگ\u200cبندی و طبقه\u200cبندی می\u200cدهید، نمودار اضافه می\u200cکنید و نتیجه را با لینک یا iframe در وب\u200cسایت می\u200cگذارید.\n\nاز همان نقشه اسلاید برای جلسه، PDF برای چاپ و پروژه\u200cی QGIS یا WMS/WFS برای همکار فنی بگیرید.',
    audiences=(
        'city',
        'student',
        'edu',
    ),
    steps=(
        ('نقشه\u200cی تازه', 'عنوان بدهید و جدول\u200cها را انتخاب کنید.'),
        ('طراحی', 'رنگ، اندازه و پنجره\u200cی اطلاعات هر لایه.'),
        ('اشتراک', 'لینک عمومی، iframe یا خروجی چاپ.'),
    ),
    guides=(
        ('maps', 'نقشه چندلایه'),
        ('mapcharts', 'نمودار روی نقشه'),
        ('mapshow', 'ارائه، چاپ و مقایسه'),
    ),
    kb=(
        ('multi-layer-maps', 'نقشه چندلایه'),
        ('map-charts', 'نمودار نقشه'),
        ('map-slides-present', 'اسلاید و ارائه'),
    ),
))
