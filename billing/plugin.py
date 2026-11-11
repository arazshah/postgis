"""مانیفست پلاگین «پلن و صورتحساب» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("billing", "پلن و صورتحساب", kind="system", requires=("accounts", "databases"))

nav.admin_item("finance", "billing.invoice", None, plugin=plugin.id, order=10)
nav.admin_item("finance", "billing.planvoucher", None, plugin=plugin.id, order=20)
nav.admin_badge("billing.invoice", "billing.plugin.pending_invoices", plugin=plugin.id)


def pending_invoices() -> int:
    from .models import Invoice

    return Invoice.objects.filter(status=Invoice.Status.REVIEW).count()
