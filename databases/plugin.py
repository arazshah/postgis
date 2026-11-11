"""مانیفست پلاگین «پایگاه داده و داده» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import admin as admin_dash
from kernel import dataio, home, jobs, nav, plugins, tenantdb, workspace

plugin = plugins.register("databases", "پایگاه داده و داده", kind="system", requires=("accounts", "jobs"))

# دروازه‌ی داده‌ی مشتری: هسته از این پلاگین می‌پرسد چگونه وصل شود و کاتالوگ کامل کدام کلاس است
from .gateway import GdalProvider, PostgisConnector, TeamProvider  # noqa: E402

tenantdb.set_connector(PostgisConnector())
tenantdb.set_catalog("databases.explorer.Explorer")
workspace.set_provider(TeamProvider())
dataio.set_provider(GdalProvider())

jobs.register_kind("import", "ورود فایل", "databases.jobs.do_import", plugin=plugin.id,
                   destination="databases:explore", done_title="دریافت و ورود فایل تمام شد")
jobs.register_tick("import_drafts", "databases.jobs.expire_import_drafts", plugin=plugin.id, order=45)
jobs.register_kind("find", "ذخیره‌ی نتیجه‌ی یافتن عارضه", "databases.jobs.do_find", plugin=plugin.id,
                   destination="databases:explore")

nav.ws_section("top", "نمای کلی و اتصال", "databases:detail", "home", "viewer", plugin=plugin.id, order=10)
nav.ws_section("data", "جدول‌ها", "databases:explore", "table", "viewer", plugin=plugin.id, order=10, views=("databases:explore", "databases:explore_table"))
nav.ws_section("data", "یافتن عارضه", "databases:find", "search", "viewer", plugin=plugin.id, order=20)
nav.ws_section("data", "اجرای SQL", "databases:explore_sql", "code", "viewer", plugin=plugin.id, order=30)
nav.ws_section("data", "ورود فایل", "databases:import", "upload", "editor", plugin=plugin.id, order=40, views=("databases:import", "databases:import_review"))
nav.ws_section("data", "سلامت داده", "databases:explore_health", "pulse", "viewer", plugin=plugin.id, order=70)
nav.ws_section("manage", "تیم و کاربران", "databases:team", "users", "owner", plugin=plugin.id, order=10)
nav.ws_section("manage", "بکاپ و بازگردانی", "databases:backups", "clock", "owner", plugin=plugin.id, order=20)
nav.ws_section("manage", "مصرف و کارایی", "databases:usage", "gauge", "owner", plugin=plugin.id, order=30)
nav.home_action("data", "جدول‌ها و داده‌ها", "جدول‌ها، ستون‌ها و روی نقشه را ببین؛ خروجی CSV و GeoJSON بگیر",
                "databases:explore", "table", plugin=plugin.id, order=10)
nav.home_action("data", "اجرای SQL", "کوئری بنویس و نتیجه را همان‌جا ببین (به‌طور پیش‌فرض فقط‌خواندنی)",
                "databases:explore_sql", "code", plugin=plugin.id, order=20)
nav.home_action("data", "ورود فایل", "Shapefile، GeoPackage، GeoJSON، KML یا CSV را آپلود کن",
                "databases:import", "upload", plugin=plugin.id, order=30)
nav.home_action("manage", "بکاپ‌ها", "نسخه پشتیبان بگیر، دانلود کن یا بازگردانی کن",
                "databases:backups", "clock", plugin=plugin.id, order=10)
nav.home_action("manage", "مصرف و کارایی", "نمودار حجم و درخواست‌ها و پیشنهاد نمایه",
                "databases:usage", "gauge", plugin=plugin.id, order=20)
nav.home_action("manage", "تیم و دسترسی", "همکارانت را با نقش مشاهده‌گر یا ویرایشگر دعوت کن",
                "databases:team", "users", plugin=plugin.id, order=30)
nav.admin_item("customers", "databases.userdatabase", None, plugin=plugin.id, order=20)
nav.admin_item("customers", "databases.activitylog", "رویدادهای پایگاه", plugin=plugin.id, order=30)
nav.admin_item("finance", "databases.plan", "پلن‌ها و قیمت‌ها", plugin=plugin.id, order=30)
nav.admin_item("infra", "databases.databaseserver", None, plugin=plugin.id, order=10)
nav.admin_item("infra", "databases.extension", None, plugin=plugin.id, order=20)
nav.admin_quick("افزودن سرور", "server", "admin:databases_databaseserver_add", plugin=plugin.id, order=10)
nav.admin_quick("افزودن پلن", "layers", "admin:databases_plan_add", plugin=plugin.id, order=20)

admin_dash.attention("databases.admin_cards.attention", plugin=plugin.id, order=40)
admin_dash.health("databases.admin_cards.health", plugin=plugin.id, order=10)
admin_dash.kpi("databases.admin_cards.kpis", plugin=plugin.id, order=20)
admin_dash.search("databases.admin_cards.search", plugin=plugin.id, order=20)

home.feed("databases.home.feed", plugin=plugin.id, order=40)
home.step("databases.home.step_profile", plugin=plugin.id, order=10)
home.step("databases.home.step_create", plugin=plugin.id, order=20)
home.step("databases.home.step_import", plugin=plugin.id, order=30)
