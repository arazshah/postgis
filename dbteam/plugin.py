"""مانیفست پلاگین «تیم و کاربران»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbteam", "تیم و کاربران", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/team/", "dbteam.views.team_page", "team", plugin=plugin.id, order=80)

nav.ws_section("manage", "تیم و کاربران", "databases:team", "users", "owner", plugin=plugin.id, order=10)
nav.home_action("manage", "تیم و دسترسی", "همکارانت را با نقش مشاهده‌گر یا ویرایشگر دعوت کن",
                "databases:team", "users", plugin=plugin.id, order=30)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='همکاران را با نقش مشخص به پایگاه دعوت کنید',
    category='edu',
    video='team',
    rail='ریل پایگاه ← مدیریت ← تیم و کاربران',
    features=(
        'دعوت با شماره موبایل',
        'نقش مشاهده\u200cگر و ویرایشگر',
        'کاربر PostgreSQL جدا برای GeoServer و برنامه\u200cها',
        'دسترسی محدود هر کاربر',
        'پایگاه مشترک بدون اشتراک رمز',
    ),
    details='کار تیمی روی داده\u200cی مکانی یعنی هر کس به اندازه\u200cی نقشش دسترسی داشته باشد. همکار را با شماره موبایل دعوت می\u200cکنید و نقش می\u200cدهید؛ برای نرم\u200cافزارها (GeoServer، برنامه\u200cی وب) هم کاربر PostgreSQL جدا با دسترسی محدود می\u200cسازید تا رمز اصلی لو نرود.',
    audiences=(
        'org',
        'edu',
        'dev',
    ),
    steps=(
        ('دعوت کنید', 'شماره موبایل همکار را وارد کنید.'),
        ('نقش بدهید', 'مشاهده\u200cگر یا ویرایشگر.'),
        ('کاربر برنامه بسازید', 'برای GeoServer یا کد، کاربر جدا بگیرید.'),
    ),
    guides=(
        ('team', 'تیم، نقش\u200cها و کاربران'),
    ),
    kb=(
        ('team-roles', 'نقش\u200cهای تیم'),
        ('database-users', 'کاربران پایگاه داده'),
    ),
))
