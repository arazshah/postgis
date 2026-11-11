"""مانیفست پلاگین «تصویر ماهواره‌ای» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import jobs, nav, plugins
from kernel import settings as site_settings

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
