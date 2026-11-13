"""مانیفست پلاگین «بکاپ و بازگردانی»: بخشی از داده‌ی یک پایگاه که مسیرش را در فضای‌نام databases ثبت می‌کند (docs/adr/0006)."""
from kernel import nav, plugins, routes
from kernel.showcase import Showcase
from kernel.showcase import add as _showcase

plugin = plugins.register("dbbackup", "بکاپ و بازگردانی", kind="feature", requires=("databases",))

routes.add("databases", "<int:pk>/backups/", "dbbackup.views.backups", "backups", plugin=plugin.id, order=100)
routes.add("databases", "<int:pk>/backups/new/", "dbbackup.views.backup_new", "backup_new", plugin=plugin.id, order=110)
routes.add("databases", "<int:pk>/backups/<int:job_id>/download/", "dbbackup.views.backup_download", "backup_download", plugin=plugin.id, order=120)
routes.add("databases", "<int:pk>/backups/<int:job_id>/restore/", "dbbackup.views.backup_restore", "backup_restore", plugin=plugin.id, order=130)

nav.ws_section("manage", "بکاپ و بازگردانی", "databases:backups", "clock", "owner", plugin=plugin.id, order=20)
nav.home_action("manage", "بکاپ‌ها", "نسخه پشتیبان بگیر، دانلود کن یا بازگردانی کن",
                "databases:backups", "clock", plugin=plugin.id, order=10)

# ویترین بازارچه پلاگین (docs/adr/0011)
_showcase(plugin.id, Showcase(
    tagline='هر شب بکاپ، هر وقت خواستید دانلود و بازگردانی',
    category='data',
    video='backups',
    rail='ریل پایگاه ← مدیریت ← بکاپ و بازگردانی',
    features=(
        'بکاپ کامل شبانه\u200cی خودکار',
        'بکاپ دستی با یک کلیک',
        'دانلود فایل بکاپ',
        'بازگردانی با کپی ایمنی پیش از کار',
        'آزمایش بازگردانی بدون خطر برای داده\u200cی فعلی',
    ),
    details='داده\u200cی مکانی ارزشمند است و بکاپ بخش جدایی\u200cناپذیر کار حرفه\u200cای. هر شب نسخه\u200cی کامل پایگاه گرفته می\u200cشود؛ هر وقت پیش از یک کار بزرگ خواستید، بکاپ دستی بگیرید و فایلش را دانلود کنید.\n\nبازگردانی آگاهانه است: پیش از جایگزینی، یک کپی ایمنی از وضعیت فعلی ساخته می\u200cشود.',
    audiences=(
        'org',
        'dev',
        'edu',
    ),
    steps=(
        ('بکاپ بگیرید', '«بکاپ تازه» را بزنید؛ در پس\u200cزمینه ساخته می\u200cشود.'),
        ('دانلود کنید', 'فایل را برای نگهداری بیرونی بگیرید.'),
        ('بازگردانی', 'هر بکاپ را انتخاب و پایگاه را به آن برگردانید.'),
    ),
    guides=(
        ('backups', 'بکاپ، دانلود و بازگردانی'),
    ),
    kb=(
        ('backups-overview', 'بکاپ\u200cها'),
        ('backup-restore', 'بازگردانی'),
        ('backup-safety-copy', 'کپی ایمنی'),
    ),
))
