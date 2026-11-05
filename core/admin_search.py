"""جست‌وجوی سراسری رکوردها در پنل مدیریت (Ctrl+K): کاربر، پایگاه داده، فاکتور، تیکت."""
from django.contrib import admin
from django.db.models import Q
from django.http import JsonResponse
from django.urls import reverse

LIMIT = 5


def _rows(request, qs, title, sub, group, icon):
    model = qs.model
    ma = admin.site._registry.get(model)
    if ma is None or not ma.has_view_or_change_permission(request):
        return []
    return [{"t": title(o), "s": sub(o), "g": group, "i": icon,
             "u": reverse(f"admin:{model._meta.app_label}_{model._meta.model_name}_change", args=[o.pk])}
            for o in qs[:LIMIT]]


def search(request):
    q = (request.GET.get("q") or "").strip()
    if len(q) < 2 or not request.user.is_staff:
        return JsonResponse({"rows": []})
    from accounts.models import SiteUser
    from billing.models import Invoice
    from databases.models import UserDatabase
    from support.models import Ticket

    rows = []
    rows += _rows(request, SiteUser.objects.filter(
        Q(phone__icontains=q) | Q(full_name__icontains=q) | Q(email__icontains=q) | Q(organization__icontains=q)),
        lambda o: o.full_name or o.phone, lambda o: o.phone, "کاربر", "user")
    rows += _rows(request, UserDatabase.objects.select_related("owner").filter(
        Q(db_name__icontains=q) | Q(label__icontains=q)),
        lambda o: o.db_name, lambda o: str(o.owner), "پایگاه داده", "db")
    rows += _rows(request, Invoice.objects.select_related("user").filter(
        Q(number__icontains=q) | Q(tracking_code__icontains=q) | Q(gateway_ref__icontains=q)),
        lambda o: f"فاکتور {o.number}", lambda o: f"{o.amount_toman:,} تومان", "فاکتور", "card")
    rows += _rows(request, Ticket.objects.select_related("user").filter(
        Q(number__icontains=q) | Q(subject__icontains=q)),
        lambda o: o.subject, lambda o: f"تیکت {o.number}", "تیکت", "life")
    return JsonResponse({"rows": rows})
