"""مانیفست پلاگین «امکانات سازمانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("enterprise", "امکانات سازمانی", kind="feature", requires=("databases", "jobs"))

jobs.register_kind("geoserver", "GeoServer اختصاصی", "enterprise.jobs.do_geoserver", plugin=plugin.id,
                   destination="enterprise:page")
jobs.register_kind("raster", "پردازش رستر", "enterprise.jobs.do_raster", plugin=plugin.id,
                   destination="enterprise:page")
jobs.register_kind("clone", "کپی پایگاه داده", "enterprise.jobs.do_clone", plugin=plugin.id,
                   destination="enterprise:page")

nav.ws_section("manage", "امکانات سازمانی", "enterprise:page", "server", "owner", plugin=plugin.id, order=40)
nav.admin_item("infra", "enterprise.geoserverinstance", None, plugin=plugin.id, order=40)
nav.admin_item("infra", "enterprise.raster", None, plugin=plugin.id, order=50)
jobs.register_tick("rasters_dir", "enterprise.jobs.tick_rasters_dir", plugin=plugin.id, order=5)
jobs.register_tick("snapshots", "enterprise.services.schedule_snapshots", plugin=plugin.id, order=70)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='GeoServer اختصاصی، رستر و کپی آزمایشی برای سازمان\u200cها',
    category='edu',
    video='enterprise',
    rail='ریل پایگاه ← مدیریت ← امکانات سازمانی',
    features=(
        'GeoServer اختصاصی برای پایگاه شما',
        'سرویس رستر و GeoTIFF',
        'بکاپ با فاصله\u200cی چند ساعت',
        'کپی آزمایشی پایگاه از هر بکاپ',
        'پشتیبانی اولویت\u200cدار',
    ),
    details='سازمان\u200cها اغلب به محیط اختصاصی، رستر و آزمایش بدون خطر روی داده\u200cی واقعی نیاز دارند. امکانات سازمانی یک GeoServer جدا، سرویس رستر برای GeoTIFF و کپی آزمایشی از بکاپ را کنار هم می\u200cگذارد تا تغییر در محیط واقعی بی\u200cدردسر باشد.',
    audiences=(
        'org',
        'city',
        'dev',
    ),
    steps=(
        ('پلن سازمانی', 'امکانات با پلن فعال می\u200cشود.'),
        ('GeoServer را راه بیندازید', 'با یک کلیک.'),
        ('کپی آزمایشی بگیرید', 'از هر بکاپ.'),
    ),
    guides=(
        ('enterprise', 'امکانات سازمانی'),
    ),
    kb=(
        ('enterprise-overview', 'امکانات سازمانی'),
        ('enterprise-geoserver', 'GeoServer اختصاصی'),
        ('enterprise-clone', 'کپی آزمایشی'),
    ),
))
