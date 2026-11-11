"""سهم «پشتیبانی» در داشبورد و جست‌وجوی پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.db.models import Q
from django.urls import reverse

from kernel import dash as dash

from .models import Ticket

OPEN_URL = ("admin:support_ticket_changelist", "?status__exact=open")


def _open() -> int:
    return Ticket.objects.filter(status=Ticket.Status.OPEN).count()


def attention():
    n = _open()
    return [dash.item("warn", f"{n} تیکت منتظر پاسخ شماست", "پاسخ", dash.url(*OPEN_URL))] if n else []


def kpis():
    n = _open()
    return [{"label": "تیکت منتظر پاسخ", "value": n, "sub": "پشتیبانی" if n else "همه پاسخ داده شده",
             "url": dash.url(*OPEN_URL), "bad": n > 0}]


def activity():
    return [{"at": t.created_at, "icon": "life", "kind": "تیکت", "text": t.subject,
             "url": reverse("admin:support_ticket_change", args=[t.pk])} for t in Ticket.objects.order_by("-created_at")[:4]]


def search(request, q):
    return dash.rows(request, Ticket.objects.select_related("user").filter(
        Q(number__icontains=q) | Q(subject__icontains=q)),
        lambda o: o.subject, lambda o: f"تیکت {o.number}", "تیکت", "life")
