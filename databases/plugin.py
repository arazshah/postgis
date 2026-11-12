"""مانیفست پلاگین «پایگاه داده و داده» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import dataio, home, nav, plugins, tenantdb, workspace

plugin = plugins.register("databases", "پایگاه داده و داده", kind="system", requires=("accounts", "jobs"))

# دروازه‌ی داده‌ی مشتری: هسته از این پلاگین می‌پرسد چگونه وصل شود و کاتالوگ کامل کدام کلاس است
from .gateway import GdalProvider, PostgisConnector, TeamProvider  # noqa: E402

tenantdb.set_connector(PostgisConnector())
tenantdb.set_catalog("databases.explorer.Explorer")
workspace.set_provider(TeamProvider())
dataio.set_provider(GdalProvider())


nav.ws_section("top", "نمای کلی و اتصال", "databases:detail", "home", "viewer", plugin=plugin.id, order=10)
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
