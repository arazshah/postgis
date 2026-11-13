"""مانیفست پلاگین «تصویر ماهواره‌ای» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins
from kernel import settings as site_settings
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("satellite", "تصویر ماهواره‌ای", kind="feature", requires=("databases", "enterprise", "jobs"))

jobs.register_kind("satellite", "دریافت تصویر ماهواره‌ای", "satellite.jobs.do_satellite", plugin=plugin.id,
                   destination="satellite:index")
jobs.register_kind("sat_analysis", "تحلیل ماهواره‌ای", "satellite.jobs.do_sat_analysis", plugin=plugin.id,
                   destination="satellite:index")

nav.ws_section("data", "تصویر ماهواره‌ای", "satellite:index", "satellite", "viewer", plugin=plugin.id, order=60)
jobs.register_tick("satellite", "satellite.services.poll", plugin=plugin.id, order=80)
jobs.register_tick("monitors", "satellite.monitor_service.run_due", plugin=plugin.id, order=90)

site_settings.tab("sat", "ماهواره", "satellite", plugin=plugin.id, order=100, status="satellite.settings_admin.tab_status")
site_settings.section("satgate", "sat", "دروازه‌ی ماهواره (دریافت تصویر ماهواره‌ای)", plugin=plugin.id, order=90,
                      fields=("satgate_status", "satgate_url", "satgate_secret", "generate_satgate_secret", "clear_satgate_secret", "satgate_tools"),
                      description="کار سنگین تصویر ماهواره‌ای روی یک سرور کوچک خارج از ایران (دروازه) انجام می‌شود؛ راه‌اندازی آن در satgate/README.md آمده است. نشانی و کلید را اینجا بدهید، ذخیره کنید و «آزمایش اتصال» را بزنید. نیازی به تغییر متغیرهای Coolify یا اجرای دوباره‌ی سرویس نیست.")
site_settings.display("satgate_status", "وضعیت دروازه", "satellite.settings_admin.satgate_status", plugin=plugin.id)
site_settings.display("satgate_tools", "ابزار دروازه", "satellite.settings_admin.satgate_tools", plugin=plugin.id)
site_settings.tool("satgatetest", "satgate-test/", "satellite.settings_admin.satgate_test_view", plugin=plugin.id)
site_settings.on_save("satellite.settings_admin.after_save", plugin=plugin.id)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='تصویر ماهواره\u200cای رایگان و پایش سبزی (NDVI) برای محدوده\u200cی شما',
    category='agri',
    video='satellite',
    featured=7,
    rail='ریل پایگاه ← داده ← تصویر ماهواره\u200cای',
    features=(
        'Sentinel-2 و Landsat برای هر محدوده',
        'میانگین NDVI هر قطعه در طول زمان',
        'پایش خودکار و اعلان افت سبزی',
        'تحلیل آماری روی چندضلعی\u200cها',
        'باز کردن نتیجه در QGIS',
    ),
    details='تصویر ماهواره\u200cای بدون جست\u200cوجوی دستی در پایگاه\u200cهای بین\u200cالمللی: محدوده را مشخص می\u200cکنید، تصویر دریافت و در پایگاه شما نگهداری می\u200cشود. برای مزرعه یا قطعه\u200cهای کشاورزی، میانگین NDVI در گذر زمان نشان\u200cدهنده\u200cی سلامت پوشش گیاهی است.\n\nپایش خودکار اگر سبزی افت کند خبرتان می\u200cکند تا پیش از رسیدن به مرحله\u200cی بحران واکنش نشان دهید.',
    audiences=(
        'agri',
        'student',
        'org',
        'city',
    ),
    steps=(
        ('محدوده را بدهید', 'چندضلعی را روی نقشه بکشید یا لایه را انتخاب کنید.'),
        ('تصویر بگیرید', 'بازه\u200cی زمانی و ماهواره را مشخص کنید.'),
        ('پایش را روشن کنید', 'اعلان افت سبزی.'),
    ),
    guides=(
        ('satellite', 'تصویر ماهواره\u200cای و پایش'),
    ),
    kb=(
        ('satellite-imagery', 'تصویر ماهواره\u200cای'),
        ('satellite-analysis', 'تحلیل ماهواره\u200cای'),
        ('satellite-quota', 'سهمیه\u200cی ماهواره'),
    ),
))
