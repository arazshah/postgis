"""ارائه‌دهنده‌ی فروش پلاگین برای kernel.market: آگهی ← `PluginAddon` (همان فروشگاه و فاکتور افزونه‌ی موجود)."""
from kernel.market import Listing

from .models import PluginAddon


def sales_stats(addon: PluginAddon) -> dict:
    """فروش یک افزونه: شمار و مبلغ فاکتورهای پرداخت‌شده، سری ۶ ماه اخیر و فاکتورهای باز. بدون هیچ نشانی از مشتری."""
    from datetime import timedelta

    from django.db.models import Count, Sum
    from django.db.models.functions import TruncMonth
    from django.utils import timezone

    from .models import Invoice

    paid = Invoice.objects.filter(addon=addon, status=Invoice.Status.PAID)
    now = timezone.now()
    tot = paid.aggregate(n=Count("pk"), s=Sum("amount_toman"))
    m30 = paid.filter(paid_at__gte=now - timedelta(days=30)).aggregate(n=Count("pk"), s=Sum("amount_toman"))
    months = [{"month": r["m"].strftime("%Y-%m"), "count": r["n"], "amount": r["s"] or 0}
              for r in paid.filter(paid_at__isnull=False, paid_at__gte=now - timedelta(days=185)).annotate(m=TruncMonth("paid_at"))
              .values("m").annotate(n=Count("pk"), s=Sum("amount_toman")).order_by("m")]
    return {"listed": True, "public": addon.is_public, "price_toman": addon.price_toman, "duration_days": addon.duration_days, "scope": addon.scope,
            "trial_days": addon.trial_days, "invoices_paid": tot["n"] or 0, "revenue_total": tot["s"] or 0, "invoices_30d": m30["n"] or 0,
            "revenue_30d": m30["s"] or 0, "months": months, "invoices_open": Invoice.objects.filter(addon=addon, status__in=Invoice.OPEN).count()}


def handle(action: str, plugin_id: str, listing: Listing | None):
    addon = PluginAddon.objects.filter(plugin_id=plugin_id).order_by("pk").first()
    if action == "stats":
        return sales_stats(addon) if addon is not None else {"listed": False}
    if action == "remove":
        if addon is not None:
            addon.is_public = False
            addon.save(update_fields=["is_public"])
        return
    scope = PluginAddon.Scope.USER if listing.scope == "user" else PluginAddon.Scope.WORKSPACE
    fields = {"title": listing.title[:80], "description": listing.summary[:240], "price_toman": int(listing.price_toman),
              "duration_days": int(listing.duration_days), "scope": scope, "trial_days": int(listing.trial_days),
              "limits": dict(listing.limits), "is_public": bool(listing.is_public),
              "category": listing.category, "features": list(listing.features), "details": listing.details}
    if addon is None:
        PluginAddon.objects.create(plugin_id=plugin_id, **fields)
    else:
        for k, v in fields.items():
            setattr(addon, k, v)
        addon.save()
