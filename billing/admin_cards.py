"""سهم «پلن و صورتحساب» در داشبورد و جست‌وجوی پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from datetime import timedelta

from django.db.models import Q, Sum
from django.urls import reverse
from django.utils import timezone

from kernel import admin as dash

from .models import Invoice

REVIEW_URL = ("admin:billing_invoice_changelist", "?status__exact=review")


def _review() -> int:
    return Invoice.objects.filter(status=Invoice.Status.REVIEW).count()


def attention():
    n = _review()
    return [dash.item("warn", f"{n} رسید پرداخت منتظر تأیید است", "بررسی", dash.url(*REVIEW_URL))] if n else []


def health():
    from core.models import SiteSettings

    from .settings_admin import tab_status

    return [dash.health_item("درگاه پرداخت", *tab_status(SiteSettings.get()),
                             dash.url("admin:core_sitesettings_changelist") + "#pay", "card")]


def kpis():
    paid = Invoice.objects.filter(status=Invoice.Status.PAID)
    revenue = sum(paid.filter(paid_at__gte=timezone.now() - timedelta(days=30)).values_list("amount_toman", flat=True))
    return [{"label": "درآمد ۳۰ روز", "value": f"{revenue:,}", "sub": "تومان",
             "spark": dash.spark(dash.series(paid, "paid_at", Sum("amount_toman"))),
             "url": dash.url("admin:billing_invoice_changelist", "?status__exact=paid")}]


def kpi_review():
    n = _review()
    return [{"label": "رسید منتظر تأیید", "value": n, "sub": "نیازمند تصمیم شما" if n else "چیزی در صف نیست",
             "url": dash.url(*REVIEW_URL), "bad": n > 0}]


def activity():
    return [{"at": i.paid_at, "icon": "card", "kind": "پرداخت", "text": f"{i.amount_toman:,} تومان",
             "url": reverse("admin:billing_invoice_change", args=[i.pk])}
            for i in Invoice.objects.filter(status=Invoice.Status.PAID).exclude(paid_at=None).order_by("-paid_at")[:4]]


def search(request, q):
    return dash.rows(request, Invoice.objects.select_related("user").filter(
        Q(number__icontains=q) | Q(tracking_code__icontains=q) | Q(gateway_ref__icontains=q)),
        lambda o: f"فاکتور {o.number}", lambda o: f"{o.amount_toman:,} تومان", "فاکتور", "card")
