"""مانیفست پلاگین «برداشت میدانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import nav, plugins
from kernel import settings as site_settings
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("survey", "برداشت میدانی", kind="feature", requires=("databases",))

nav.ws_section("share", "برداشت میدانی", "survey:index", "target", "viewer", plugin=plugin.id, order=30, views=("survey:index", "survey:studio"), visible="survey.plugin.enabled")
nav.home_action("data", "برداشت میدانی", "با GPS یا گیرنده RTK در میدان نقطه برداشت کن؛ آفلاین هم کار می‌کند",
                "survey:index", "target", plugin=plugin.id, order=40, visible="survey.plugin.enabled")
nav.admin_item("publish", "survey.surveyproject", None, plugin=plugin.id, order=60)
nav.admin_item("publish", "survey.gnssdriver", None, plugin=plugin.id, order=70)
nav.admin_item("publish", "survey.ntripprofile", None, plugin=plugin.id, order=80)

site_settings.section("survey", "map", "برداشت میدانی", plugin=plugin.id, order=130,
                      fields=("survey_enabled",),
                      description="نقشه‌برداری و اتصال گیرنده GNSS. تا خاموش است هیچ‌چیز برای کاربران دیده نمی‌شود.")
admin_dash.report_sheet("survey.reports.sheets", plugin=plugin.id, order=50)


def enabled() -> bool:
    """برداشت میدانی با کلید تنظیمات سایت روشن و خاموش می‌شود."""
    from core.models import SiteSettings

    return bool(SiteSettings.get().survey_enabled)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='با GPS گوشی یا گیرنده\u200cی دقیق در میدان برداشت کنید',
    category='survey',
    video='survey',
    featured=6,
    rail='ریل پایگاه ← تحلیل و انتشار ← برداشت میدانی',
    features=(
        'نقطه، خط و چندضلعی با GPS گوشی',
        'گیرنده\u200cی RTK و تصحیح NTRIP',
        'کار آفلاین با نقشه\u200cی ذخیره\u200cشده',
        'منحنی میزان و حجم خاکبرداری',
        'خروجی DXF، CSV و GeoJSON',
        'داده مستقیم در جدول PostGIS',
    ),
    details='برداشت میدانی مرز کار دفتری و میدانی را برمی\u200cدارد: پروژه می\u200cسازید، در میدان نقطه و خط می\u200cگیرید و داده بی\u200cواسطه در پایگاه می\u200cنشیند. گیرنده\u200cی GNSS را با سریال یا بلوتوث وصل کنید و تصحیح RTK را از کستر NTRIP بگیرید.\n\nمحاسبه\u200cهای نقشه\u200cبرداری مثل فاصله، آزیموت، مساحت، پیاده\u200cسازی نقطه، منحنی میزان و حجم هم در همین پلاگین است و خروجی DXF مستقیم به نرم\u200cافزار نقشه\u200cکشی می\u200cرود.',
    audiences=(
        'survey',
        'agri',
        'city',
    ),
    steps=(
        ('پروژه بسازید', 'جدول مقصد را انتخاب کنید.'),
        ('برداشت کنید', 'با گوشی یا گیرنده\u200cی RTK.'),
        ('خروجی بگیرید', 'DXF، CSV یا GeoJSON.'),
    ),
    guides=(
        ('survey', 'برداشت میدانی'),
        ('gnss', 'گیرنده RTK و NTRIP'),
        ('surface', 'منحنی میزان و حجم'),
    ),
    kb=(
        ('survey-overview', 'برداشت میدانی'),
        ('survey-ntrip-rtk', 'RTK و NTRIP'),
        ('survey-offline', 'کار آفلاین'),
        ('survey-cogo-stakeout', 'پیاده\u200cسازی نقطه'),
    ),
))
