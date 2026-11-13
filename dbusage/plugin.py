"""مانیفست پلاگین «مصرف و کارایی»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbusage", "مصرف و کارایی", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/usage/", "dbusage.views.usage_page", "usage", plugin=plugin.id, order=90)

nav.ws_section("manage", "مصرف و کارایی", "databases:usage", "gauge", "owner", plugin=plugin.id, order=30)
nav.home_action("manage", "مصرف و کارایی", "نمودار حجم و درخواست‌ها و پیشنهاد نمایه",
                "databases:usage", "gauge", plugin=plugin.id, order=20)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='ببینید پایگاهتان چقدر مصرف می\u200cکند و چطور سریع\u200cتر شود',
    category='data',
    video='usage',
    rail='ریل پایگاه ← مدیریت ← مصرف و کارایی',
    features=(
        'حجم و رشد پایگاه داده',
        'بزرگ\u200cترین جدول\u200cها',
        'کوئری\u200cهای در حال اجرا',
        'درخواست\u200cهای نقشه و API',
        'راهنمای اتصال PgBouncer برای برنامه\u200cها',
    ),
    details='مصرف و کارایی به شما می\u200cگوید حجم کجا رفته، کدام جدول بزرگ شده و آیا کوئری کندی در حال اجراست. برای وب\u200cسایت\u200cها و برنامه\u200cهایی که اتصال زیاد باز می\u200cکنند، اطلاعات PgBouncer آماده است.',
    audiences=(
        'dev',
        'org',
        'edu',
    ),
    steps=(
        ('مصرف را ببینید', 'نمودار حجم و رشد را بخوانید.'),
        ('جدول بزرگ را پیدا کنید', 'فهرست بزرگ\u200cترین جدول\u200cها.'),
        ('اتصال برنامه را بهینه کنید', 'نشانی PgBouncer را در برنامه بگذارید.'),
    ),
    guides=(
        ('usage', 'مصرف و کارایی'),
        ('limits', 'محدودیت\u200cهای پلن'),
    ),
    kb=(
        ('usage-and-performance', 'مصرف و کارایی'),
        ('pgbouncer', 'PgBouncer'),
    ),
))
