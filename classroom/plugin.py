"""مانیفست پلاگین «کلاس درس» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import home, jobs, nav, plugins
from kernel import settings as site_settings
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("classroom", "کلاس درس", kind="feature", requires=("databases", "maps"))

nav.admin_item("customers", "classroom.classroom", None, plugin=plugin.id, order=40)
nav.admin_item("customers", "classroom.contract", None, plugin=plugin.id, order=50)
nav.admin_item("customers", "classroom.contractrequest", None, plugin=plugin.id, order=60)
jobs.register_tick("classes", "classroom.services.tick", plugin=plugin.id, order=10)

site_settings.section("class_plan", "users", "پلن کلاس و دانشگاه", plugin=plugin.id, order=170,
                      fields=("class_price_per_student",))

home.context("classroom.home.context", plugin=plugin.id, order=10)
admin_dash.report_sheet("classroom.reports.sheets", plugin=plugin.id, order=40)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='برای هر دانشجو یک پایگاه PostGIS؛ تمرین و نمره در یک صفحه',
    category='edu',
    video='classroom',
    featured=9,
    rail='سایت ← کلاس درس',
    features=(
        'پایگاه داده\u200cی شخصی با داده\u200cی تمرینی برای هر دانشجو',
        'ساخت کلاس و دعوت با کد',
        'تمرین، تحویل، نمره و بازخورد',
        'برگرداندن تمرین برای اصلاح',
        'خروجی نمره\u200cها به CSV',
        'بکاپ همه\u200cی دانشجوها در پایان ترم',
    ),
    details='استاد کلاس را می\u200cسازد و کد را به دانشجوها می\u200cدهد؛ هر دانشجو بی\u200cنیاز از نصب نرم\u200cافزار پایگاه شخصی با داده\u200cی تمرینی می\u200cگیرد. تمرین\u200cها، تحویل\u200cها و نمره\u200cها در یک صفحه مدیریت می\u200cشوند.\n\nپایان ترم از همه\u200cی پایگاه\u200cها بکاپ گرفته می\u200cشود و هزینه بر اساس تعداد دانشجو محاسبه می\u200cشود.',
    audiences=(
        'edu',
        'student',
        'org',
    ),
    steps=(
        ('کلاس بسازید', 'کد کلاس را بدهید.'),
        ('تمرین بگذارید', 'تحویل\u200cها را بررسی کنید.'),
        ('نمره بدهید', 'خروجی CSV بگیرید.'),
    ),
    guides=(
        ('classroom-teacher', 'استاد: کلاس و تمرین'),
        ('classroom-student', 'دانشجو: ورود و تحویل'),
    ),
    kb=(
        ('classroom-overview', 'کلاس درس'),
        ('classroom-create', 'ساخت کلاس'),
        ('classroom-grade', 'نمره\u200cدهی'),
    ),
))
