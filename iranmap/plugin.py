"""مانیفست پلاگین «داده آماده و نقشه پایه ایران» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("iranmap", "داده آماده و نقشه پایه ایران", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("basemap", "ساخت نقشه پایه ایران", "iranmap.tasks.do_basemap", plugin=plugin.id,
                   destination="iranmap:ready", quiet_when_auto=True)
jobs.register_kind("osm_refresh", "به‌روزرسانی داده OSM ایران", "iranmap.tasks.do_osm_refresh", plugin=plugin.id,
                   destination="iranmap:ready", quiet_when_auto=True,
                   done_title="دریافت داده آماده ایران تمام شد")
jobs.register_kind("osm_import", "داده آماده ایران", "iranmap.tasks.do_osm_import", plugin=plugin.id,
                   destination="iranmap:ready", done_title="دریافت داده آماده ایران تمام شد")

nav.ws_section("data", "داده آماده ایران", "iranmap:ready", "pin", "editor", plugin=plugin.id, order=50)
nav.admin_item("infra", "iranmap.area", None, plugin=plugin.id, order=60)
jobs.register_tick("map_data", "iranmap.tasks.schedule", plugin=plugin.id, order=60)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='داده\u200cی آماده\u200cی OpenStreetMap ایران و نقشه\u200cی پایه\u200cی فارسی',
    category='data',
    video='ready',
    featured=8,
    rail='ریل پایگاه ← داده ← داده آماده ایران',
    features=(
        'معابر، ساختمان، کاربری زمین و مکان\u200cهای مهم',
        'مرز هر استان، شهرستان و شهر',
        'نقشه\u200cی پایه\u200cی فارسی آفلاین',
        'شبکه\u200cی آماده\u200cی pgRouting',
        'به\u200cروزرسانی دوره\u200cای',
    ),
    details='به\u200cجای دریافت و پردازش فایل\u200cهای حجیم OSM، منطقه\u200cی مورد نظر (کشور، استان، شهرستان یا شهر) را انتخاب می\u200cکنید و داده\u200cی آماده در پایگاه خودتان می\u200cنشیند. شبکه\u200cی معابر برای مسیریابی و حوزه\u200cی دسترسی آماده است و نقشه\u200cی پایه\u200cی فارسی بدون وابستگی به سرویس خارجی نمایش داده می\u200cشود.\n\nمنبع داده OpenStreetMap است و نشان\u200cگذاری ODbL رعایت می\u200cشود.',
    audiences=(
        'student',
        'city',
        'dev',
        'org',
    ),
    steps=(
        ('منطقه را انتخاب کنید', 'استان یا شهر.'),
        ('دریافت کنید', 'کار در پس\u200cزمینه انجام می\u200cشود.'),
        ('تحلیل کنید', 'با ابزارهای مسیر و حوزه\u200cی دسترسی.'),
    ),
    guides=(
        ('ready', 'داده آماده ایران و مسیریابی'),
    ),
    kb=(
        ('osm-data-overview', 'داده\u200cی OSM ایران'),
        ('routing-shortest-path', 'کوتاه\u200cترین مسیر'),
        ('service-area', 'حوزه\u200cی دسترسی'),
        ('persian-basemap', 'نقشه\u200cی پایه\u200cی فارسی'),
    ),
))
