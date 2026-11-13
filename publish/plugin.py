"""مانیفست پلاگین «انتشار نقشه و API» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import events, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("publish", "انتشار نقشه و API", kind="feature", requires=("databases",))

nav.ws_section("share", "نقشه و API", "publish:manage", "globe", "editor", plugin=plugin.id, order=50, views=("publish:manage", "publish:map_builder"))
nav.ws_section("share", "WMS و WFS", "publish:ows", "cube", "editor", plugin=plugin.id, order=60, views=("publish:ows", "publish:ows_detail"))
nav.home_action("share", "انتشار نقشه و API", "لایه را با لینک عمومی، کاشی برداری یا API در وب بگذار",
                "publish:manage", "globe", plugin=plugin.id, order=20)
nav.admin_item("publish", "publish.service", None, plugin=plugin.id, order=10)
nav.admin_item("publish", "publish.apikey", None, plugin=plugin.id, order=20)
nav.admin_item("publish", "publish.dailyusage", None, plugin=plugin.id, order=30)
nav.admin_item("publish", "publish.owsproject", None, plugin=plugin.id, order=40)

events.listen(events.WORKSPACE_DELETED, "publish.events.workspace_deleted", plugin=plugin.id)
events.listen(events.TABLE_DROPPED, "publish.events.table_dropped", plugin=plugin.id, order=20)
events.listen(events.TABLE_RENAMED, "publish.events.table_renamed", plugin=plugin.id, order=20)
events.listen(events.TABLE_USAGE, "publish.events.table_usage", plugin=plugin.id, order=20)
events.listen(events.USAGE_CARDS, "publish.events.usage_cards", plugin=plugin.id, order=20)
admin_dash.report_sheet("publish.reports.sheets", plugin=plugin.id, order=21)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='هر لایه را بدون GeoServer برای وب و QGIS منتشر کنید',
    category='publish',
    video='publish',
    featured=5,
    rail='ریل پایگاه ← تحلیل و انتشار ← نقشه و API',
    features=(
        'کاشی برداری و OGC API Features',
        'خوانش در MapLibre، Leaflet، OpenLayers، QGIS و ArcGIS',
        'عمومی یا خصوصی با کلید API',
        'WMS و WFS با QGIS Server',
        'سقف روزانه و آمار استفاده',
    ),
    details='با یک کلیک جدول مکانی به سرویس وب تبدیل می\u200cشود: کاشی برداری برای نقشه\u200cهای سریع، OGC API Features برای داده و کلید API برای کنترل دسترسی. برنامه\u200cنویس نمونه\u200cکد آماده\u200cی MapLibre و Leaflet را می\u200cگیرد.\n\nبرای کسانی که سبک دقیق QGIS می\u200cخواهند، WMS/WFS هم از همان پایگاه بدون نصب GeoServer ارائه می\u200cشود.',
    audiences=(
        'dev',
        'city',
        'org',
        'student',
    ),
    steps=(
        ('لایه را منتشر کنید', 'جدول را انتخاب و گزینه\u200cی انتشار را بزنید.'),
        ('کلید بسازید', 'برای حالت خصوصی.'),
        ('در برنامه بخوانید', 'نشانی را در MapLibre یا QGIS بگذارید.'),
    ),
    guides=(
        ('publish', 'انتشار لایه'),
        ('wms', 'WMS و WFS'),
    ),
    kb=(
        ('publish-layer-overview', 'انتشار لایه'),
        ('vector-tiles-urls', 'کاشی برداری'),
        ('api-keys', 'کلید API'),
        ('wms-wfs-qgis-server', 'WMS و WFS'),
    ),
))
