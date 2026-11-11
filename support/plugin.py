"""مانیفست پلاگین «پشتیبانی» و سهم‌های آن در نقاط توسعه‌ی هسته (docs/adr/0004)."""
from kernel import nav, plugins

plugin = plugins.register("support", "پشتیبانی", kind="system", requires=("accounts",))

nav.admin_item("support", "support.ticket", None, plugin=plugin.id, order=10)
nav.admin_badge("support.ticket", "support.plugin.open_tickets", plugin=plugin.id)


def open_tickets() -> int:
    from .models import Ticket

    return Ticket.objects.filter(status=Ticket.Status.OPEN).count()
