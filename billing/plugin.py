"""مانیفست پلاگین «پلن و صورتحساب» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import dash as admin_dash
from kernel import home, nav, plugins
from kernel import settings as site_settings

plugin = plugins.register("billing", "پلن و صورتحساب", kind="system", requires=("accounts", "databases"))

nav.admin_item("finance", "billing.invoice", None, plugin=plugin.id, order=10)
nav.admin_item("finance", "billing.planvoucher", None, plugin=plugin.id, order=20)
nav.admin_item("finance", "billing.pluginaddon", None, plugin=plugin.id, order=30)
nav.admin_badge("billing.invoice", "billing.plugin.pending_invoices", plugin=plugin.id)

site_settings.tab("pay", "پرداخت", "card", plugin=plugin.id, order=40, status="billing.settings_admin.tab_status")
site_settings.section("pay", "pay", "پرداخت و فروش پلن‌ها", plugin=plugin.id, order=120,
                      fields=("pay_enabled", "invoice_ttl_minutes", "pay_gateway_enabled", "gateway_provider", "gateway_status", "gateway_merchant", "gateway_sandbox", "gateway_tools", "pay_manual_enabled", "pay_card_number", "pay_card_holder", "pay_bank_name", "pay_link_url", "pay_manual_note"),
                      description="قیمت پلن‌ها را از بخش «پلن‌ها» تعیین کنید. پرداخت‌های منتظر تأیید در بخش «فاکتورها» هستند.")
site_settings.display("gateway_status", "وضعیت مرچنت کد", "billing.settings_admin.gateway_status", plugin=plugin.id)
site_settings.display("gateway_tools", "ابزار درگاه", "billing.settings_admin.gateway_tools", plugin=plugin.id)
site_settings.tool("gatewaytest", "gateway-test/", "billing.settings_admin.gateway_test_view", plugin=plugin.id)

admin_dash.attention("billing.admin_cards.attention", plugin=plugin.id, order=10)
admin_dash.health("billing.admin_cards.health", plugin=plugin.id, order=50)
admin_dash.kpi("billing.admin_cards.kpis", plugin=plugin.id, order=40)
admin_dash.kpi("billing.admin_cards.kpi_review", plugin=plugin.id, order=50)
admin_dash.activity("billing.admin_cards.activity", plugin=plugin.id, order=20)
admin_dash.search("billing.admin_cards.search", plugin=plugin.id, order=30)

home.context("billing.home.context", plugin=plugin.id, order=20)
admin_dash.report_sheet("billing.reports.sheets", plugin=plugin.id, order=30)


def pending_invoices() -> int:
    from .models import Invoice

    return Invoice.objects.filter(status=Invoice.Status.REVIEW).count()
