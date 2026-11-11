"""سهم «پایگاه داده» در داشبورد و جست‌وجوی پنل مدیریت؛ در plugin.py ثبت می‌شود."""
from django.db.models import Q, Sum
from django.template.defaultfilters import filesizeformat
from django.urls import reverse

from kernel import dash as dash

from .models import DatabaseServer, UserDatabase


def _servers():
    servers = list(DatabaseServer.objects.all())
    return servers, [s for s in servers if s.last_check_ok is False]


def attention():
    servers, bad = _servers()
    out = [dash.item("bad", f"اتصال به سرور «{s.name}» برقرار نیست: {s.last_check_message[:90]}", "بررسی",
                     reverse("admin:databases_databaseserver_change", args=[s.pk])) for s in bad]
    if not servers:
        out.append(dash.item("bad", "هنوز هیچ سرور دیتابیسی تعریف نشده؛ کاربران نمی‌توانند پایگاه داده بسازند.", "افزودن سرور",
                             reverse("admin:databases_databaseserver_add")))
    return out


def health():
    servers, bad = _servers()
    if not servers:
        srv = ("bad", "تعریف نشده")
    elif bad:
        srv = ("bad", f"{len(bad)} از {len(servers)} قطع")
    else:
        srv = ("ok", f"{len(servers)} سالم")
    return [dash.health_item("سرورها", *srv, dash.url("admin:databases_databaseserver_changelist"), "server")]


def kpis():
    live = UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES)
    total_size = live.aggregate(s=Sum("size_bytes"))["s"] or 0
    readonly = live.filter(status=UserDatabase.Status.READONLY).count()
    expired = UserDatabase.objects.filter(status=UserDatabase.Status.EXPIRED).count()
    link = dash.url("admin:databases_userdatabase_changelist")
    return [
        {"label": "پایگاه داده فعال", "value": f"{live.count():,}",
         "sub": f"{readonly} پر، {expired} منقضی" if readonly or expired else "همه در وضعیت عادی",
         "url": link, "bad": bool(readonly)},
        {"label": "حجم داده مشتریان", "value": filesizeformat(total_size), "sub": "مجموع پایگاه‌های فعال", "url": link},
    ]


def search(request, q):
    return dash.rows(request, UserDatabase.objects.select_related("owner").filter(
        Q(db_name__icontains=q) | Q(label__icontains=q)),
        lambda o: o.db_name, lambda o: str(o.owner), "پایگاه داده", "db")
