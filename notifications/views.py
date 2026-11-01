from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from accounts.decorators import site_user_required

from .models import Notification

PANEL_LIMIT = 30


def _item(n: Notification) -> dict:
    return {"id": n.pk, "level": n.level, "title": n.title, "body": n.body, "detail": n.detail, "url": n.url,
            "action": n.action, "read": n.read_at is not None, "at": n.created_at.isoformat()}


@site_user_required
@require_GET
def poll(request):
    """اعلان‌های تازه (بعد از `after`) برای toast و مودال، به‌علاوه فهرست پنل و شمارندهٔ خوانده‌نشده.
    بار اول (بدون after) فقط آخرین شناسه برگردانده می‌شود تا اعلان‌های قدیمی دوباره toast نشوند."""
    mine = Notification.objects.filter(user=request.user)
    latest = mine.values_list("pk", flat=True).first() or 0
    after = request.GET.get("after", "")
    fresh = []
    if after.isdigit():
        # اعلان‌های از پیش‌خوانده (مثل پیام‌هایی که همان لحظه با مودال دیده شده‌اند) دوباره نشان داده نمی‌شوند
        fresh = [_item(n) for n in mine.filter(pk__gt=int(after), read_at__isnull=True).order_by("pk")[:10]]
    panel = request.GET.get("panel") == "1"
    return JsonResponse({"latest": latest, "unread": mine.filter(read_at__isnull=True).count(), "fresh": fresh,
                         "items": [_item(n) for n in mine[:PANEL_LIMIT]] if panel else None})


@site_user_required
@require_POST
def read(request):
    """خواندن یک اعلان (id) یا همه (بدون id)."""
    qs = Notification.objects.filter(user=request.user, read_at__isnull=True)
    pk = request.POST.get("id", "")
    if pk:
        qs = qs.filter(pk=int(pk)) if pk.isdigit() else qs.none()
    qs.update(read_at=timezone.now())
    return JsonResponse({"ok": True, "unread": Notification.objects.filter(user=request.user, read_at__isnull=True).count()})


FLASH_LEVELS = {"error": Notification.Level.ERROR, "warning": Notification.Level.WARNING,
                "success": Notification.Level.SUCCESS, "info": Notification.Level.INFO}
LOG_PER_MINUTE = 20


@site_user_required
@require_POST
def log(request):
    """پیام‌های خطا و هشدار صفحه (که با مودال دیده شدند) را در پنل اعلان‌ها هم نگه می‌دارد.
    سقف در دقیقه دارد تا صفحهٔ خراب پنل را پر نکند."""
    level = FLASH_LEVELS.get(request.POST.get("level", ""))
    title = (request.POST.get("title") or "").strip()[:160]
    if level is None or level not in (Notification.Level.ERROR, Notification.Level.WARNING) or not title:
        return JsonResponse({"ok": False}, status=400)
    recent = Notification.objects.filter(user=request.user, job__isnull=True,
                                         created_at__gte=timezone.now() - timedelta(minutes=1)).count()
    if recent >= LOG_PER_MINUTE:
        return JsonResponse({"ok": False}, status=429)
    n = Notification.objects.create(user=request.user, level=level, title=title, body=(request.POST.get("body") or "")[:1000],
                                    read_at=timezone.now())
    return JsonResponse({"ok": True, "id": n.pk})
