"""مانیفست پلاگین «حساب و ورود» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import nav, plugins, stepup
from kernel import settings as site_settings

plugin = plugins.register("accounts", "حساب و ورود", kind="system")

nav.admin_item("customers", "accounts.siteuser", None, plugin=plugin.id, order=10)
nav.admin_item("settings", "accounts.adminuser", None, plugin=plugin.id, order=40)
nav.admin_item("settings", "auth.group", None, plugin=plugin.id, order=50)
nav.admin_item("settings", "accounts.otpcode", None, plugin=plugin.id, order=60)

site_settings.tab("sms", "پیامک و ورود", "bell", plugin=plugin.id, order=50, status="accounts.settings_admin.tab_status")
site_settings.section("sms", "sms", "پنل پیامک (sms.ir)", plugin=plugin.id, order=180,
                      fields=("sms_backend", "api_key_status", "smsir_api_key", "clear_smsir_api_key", "smsir_template_id", "smsir_code_param", "smsir_line_number", "sms_tools"),
                      description="قالب کد تأیید را در پنل sms.ir بسازید، مثلاً «کد ورود شما: #CODE#»، و شناسه آن را اینجا وارد کنید.")
site_settings.section("otp", "sms", "رمز یک‌بار مصرف و امنیت ورود", plugin=plugin.id, order=190,
                      fields=("otp_length", "otp_ttl_seconds", "otp_resend_seconds", "otp_max_attempts", "otp_max_per_phone_hour", "otp_max_per_ip_hour"))
site_settings.display("api_key_status", "وضعیت کلید API", "accounts.settings_admin.api_key_status", plugin=plugin.id)
site_settings.display("sms_tools", "ابزار پیامک", "accounts.settings_admin.sms_tools", plugin=plugin.id)
site_settings.tool("credit", "credit/", "accounts.settings_admin.credit_view", plugin=plugin.id)
site_settings.tool("testsms", "test-sms/", "accounts.settings_admin.test_sms_view", plugin=plugin.id)

admin_dash.attention("accounts.admin_cards.attention", plugin=plugin.id, order=60)
admin_dash.health("accounts.admin_cards.health", plugin=plugin.id, order=40)
admin_dash.kpi("accounts.admin_cards.kpis", plugin=plugin.id, order=10)
admin_dash.activity("accounts.admin_cards.activity", plugin=plugin.id, order=10)
admin_dash.search("accounts.admin_cards.search", plugin=plugin.id, order=10)

from .admin_2fa import Provider as _TwoFactor  # noqa: E402

stepup.set_provider(_TwoFactor())
