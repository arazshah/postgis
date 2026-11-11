"""مانیفست پلاگین «پشتیبانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import admin as admin_dash
from kernel import nav, plugins

plugin = plugins.register("support", "پشتیبانی", kind="system", requires=("accounts",))

nav.admin_item("support", "support.ticket", None, plugin=plugin.id, order=10)
nav.admin_badge("support.ticket", "support.plugin.open_tickets", plugin=plugin.id)

admin_dash.attention("support.admin_cards.attention", plugin=plugin.id, order=20)
admin_dash.kpi("support.admin_cards.kpis", plugin=plugin.id, order=60)
admin_dash.activity("support.admin_cards.activity", plugin=plugin.id, order=30)
admin_dash.search("support.admin_cards.search", plugin=plugin.id, order=40)


def open_tickets() -> int:
    from .models import Ticket

    return Ticket.objects.filter(status=Ticket.Status.OPEN).count()
