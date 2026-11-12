"""کار دوره‌ای بازار پلاگین: هشدار نزدیک انقضا و اعلام انقضای مجوز خرید/آزمایشی (هر مرحله یک‌بار؛ تمدید از نو)."""
import datetime
import logging

from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from kernel import workspace
from kernel.models import Entitlement
from kernel.plugins import registry

log = logging.getLogger(__name__)
WARN_DAYS = 7
SOURCES = ("purchase", "trial")


def _recipient(ent):
    """مالک مجوز: کاربر، یا مالک پایگاه داده؛ سازمان/پلن/همه پیام ندارند."""
    if ent.kind == Entitlement.Kind.USER and str(ent.subject).isdigit():
        return get_user_model().objects.filter(pk=int(ent.subject), is_active=True).first()
    if ent.kind == Entitlement.Kind.WORKSPACE and str(ent.subject).isdigit():
        ws = workspace.peek(int(ent.subject))
        if ws is not None and getattr(ws, "owner_id", None):
            return get_user_model().objects.filter(pk=ws.owner_id, is_active=True).first()
    return None


def _notify(ent, subject: str, body: str) -> bool:
    user = _recipient(ent)
    if user is None:
        return False
    try:
        workspace.notify_user(user, subject, f"{body}\n{settings.CANONICAL_URL.rstrip('/')}/billing/market/")
        return True
    except Exception:  # noqa: BLE001  خطای پیامک/ایمیل نباید کار دوره‌ای را بشکند
        log.exception("expiry notice failed for entitlement %s", ent.pk)
        return False


def tick(now=None) -> dict:
    now = now or timezone.now()
    warned = expired = 0
    base = Entitlement.objects.filter(source__in=SOURCES, expires_at__isnull=False).select_related("state")
    for e in base.filter(expires_at__lte=now, notified__lt=2):
        p = registry.plugins.get(e.state.plugin_id)
        name = p.name if p else e.state.plugin_id
        _notify(e, "پایان دسترسی به پلاگین", f"دسترسی شما به «{name}» به پایان رسید. برای ادامه تمدید کنید؛ داده‌های شما حذف نمی‌شود.")
        e.notified = 2
        e.save(update_fields=["notified"])
        expired += 1
    soon = now + datetime.timedelta(days=WARN_DAYS)
    for e in base.filter(expires_at__gt=now, expires_at__lte=soon, notified__lt=1):
        p = registry.plugins.get(e.state.plugin_id)
        name = p.name if p else e.state.plugin_id
        days = max(1, (e.expires_at - now).days)
        kind = "دوره‌ی آزمایشی" if e.source == "trial" else "دسترسی"
        _notify(e, "نزدیک پایان دسترسی به پلاگین", f"{kind} شما به «{name}» حدود {days} روز دیگر تمام می‌شود.")
        e.notified = 1
        e.save(update_fields=["notified"])
        warned += 1
    return {"warned": warned, "expired": expired}
