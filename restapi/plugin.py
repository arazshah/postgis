"""مانیفست پلاگین «REST API و فرم میدانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import events, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("restapi", "REST API و فرم میدانی", kind="feature", requires=("databases", "publish"))

nav.ws_section("share", "REST API و فرم میدانی", "restapi:manage", "braces", "editor", plugin=plugin.id, order=70)
events.listen(events.TABLE_DROPPED, "restapi.events.table_dropped", plugin=plugin.id, order=30)
events.listen(events.TABLE_RENAMED, "restapi.events.table_renamed", plugin=plugin.id, order=30)
events.listen(events.TABLE_USAGE, "restapi.events.table_usage", plugin=plugin.id, order=30)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='داده را از اپ بخوانید و بنویسید؛ با فرم موبایلی در میدان جمع کنید',
    category='publish',
    video='rest',
    rail='ریل پایگاه ← تحلیل و انتشار ← REST API و فرم میدانی',
    features=(
        'خواندن و نوشتن جدول با REST',
        'کلید API با دسترسی خواندن یا نوشتن',
        'فرم موبایلی با GPS',
        'کار آفلاین در میدان',
        'ثبت مستقیم در جدول PostGIS',
    ),
    details='REST API جدول\u200cها را برای اپلیکیشن وب، موبایل و اسکریپت باز می\u200cکند و دسترسی را با کلید و سطح خواندن/نوشتن کنترل می\u200cکنید. فرم میدانی هم صفحه\u200cای موبایلی است که مأمور میدانی با GPS گوشی داده را ثبت می\u200cکند، حتی بدون اینترنت.',
    audiences=(
        'dev',
        'survey',
        'agri',
    ),
    steps=(
        ('کلید بسازید', 'سطح دسترسی را تعیین کنید.'),
        ('فرم را بسازید', 'ستون\u200cها و فیلد موقعیت.'),
        ('لینک را بدهید', 'مأمور میدانی از گوشی پر می\u200cکند.'),
    ),
    guides=(
        ('rest', 'REST API و فرم میدانی'),
    ),
    kb=(
        ('rest-api-overview', 'REST API'),
        ('rest-write-access', 'دسترسی نوشتن'),
        ('field-form', 'فرم میدانی'),
    ),
))
