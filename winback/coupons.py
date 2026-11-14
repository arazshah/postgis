"""تخفیف بازگشت روی فاکتور (از طریق `kernel.pricing`؛ بدون کد دستی و بدون دانستن billing)."""
from django.utils import timezone

from .models import Coupon

DEAD = ("expired", "cancelled", "rejected")  # فاکتوری که پرداخت نشد، تخفیف را آزاد می‌کند (تا پایان مهلت)


def _valid(user):
    now = timezone.now()
    qs = Coupon.objects.filter(user=user, expires_at__gt=now).select_related("invoice")
    return [c for c in qs if c.invoice is None or c.invoice.status in DEAD]


def quote(user, amount: int):
    best = max(_valid(user), key=lambda c: c.percent, default=None)
    if best is None:
        return None
    return amount * (100 - best.percent) // 100, f"تخفیف بازگشت {best.percent}٪", best.pk


def bind(token, invoice) -> None:
    Coupon.objects.filter(pk=token).update(invoice=invoice)
