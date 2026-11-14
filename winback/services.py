"""موتور بازگشت: ساخت فهرست شبانه، تأیید و زمان‌بندی، ارسال، اندازه‌گیری و نتیجه.

قاعده‌ها: رضایت (پیش‌فرض عضو، لغو آسان)، سقف ۱ پیام در ۷ روز و ۳ در ۳۰ روز، پنجره‌ی زمانی مجاز،
گروه کنترل برای سنجش اثر واقعی، توقف خودکار به‌محض ورود، و هیچ ارسالی بدون تأیید مدیر.
"""
from __future__ import annotations

import datetime
import hashlib
import logging
import zlib

from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from kernel import conf, entitlements

from . import routes, timing
from .models import Batch, Message, Preference, Route

log = logging.getLogger(__name__)
PLUGIN = "winback"
WEEK_CAP, MONTH_CAP, WINDOW_DAYS, PER_TICK, PLAN_HOUR = 1, 3, 7, 20, 5


def sync_routes() -> None:
    for key in routes.DEFS:
        Route.objects.get_or_create(key=key)


def switch_on() -> bool:
    return bool(conf.get(PLUGIN, "enabled"))


def wants(user) -> bool:
    pref = Preference.objects.filter(user=user).first()
    return pref is None or pref.marketing


def set_pref(user, marketing: bool) -> None:
    Preference.objects.update_or_create(user=user, defaults={"marketing": marketing})
    if not marketing:
        Message.objects.filter(user=user, status__in=[Message.Status.PENDING, Message.Status.SCHEDULED]).update(
            status=Message.Status.SKIPPED, reason="لغو توسط کاربر")


def _is_control(user, key: str, day: datetime.date) -> bool:
    pct = int(conf.get(PLUGIN, "control_percent") or 0)
    digest = hashlib.sha256(f"{user.pk}:{key}:{day}".encode()).digest()
    return digest[0] * 100 // 256 < pct


def _capped(user, now) -> bool:
    sent = Message.objects.filter(user=user, status=Message.Status.SENT)
    return (sent.filter(sent_at__gte=now - datetime.timedelta(days=7)).count() >= WEEK_CAP
            or sent.filter(sent_at__gte=now - datetime.timedelta(days=30)).count() >= MONTH_CAP)


def _eligible(user, d: routes.RouteDef, now) -> bool:
    if not wants(user) or _capped(user, now):
        return False
    busy = Message.objects.filter(user=user, status__in=[Message.Status.PENDING, Message.Status.SCHEDULED]).exists()
    recent = Message.objects.filter(user=user, route_key=d.key, created_at__gte=now - datetime.timedelta(days=d.cooldown_days)
                                    ).exclude(status__in=[Message.Status.SKIPPED, Message.Status.FAILED]).exists()
    return not busy and not recent


def plan_batches(now=None) -> list[Batch]:
    """برای هر مسیر روشن (با قالب) حداکثر یک دسته‌ی منتظر تأیید در روز می‌سازد."""
    now = now or timezone.now()
    sync_routes()
    cap = int(conf.get(PLUGIN, "max_batch") or 300)
    today = now.astimezone(timing.TZ).date()
    made = []
    for route in Route.objects.filter(enabled=True).exclude(template_id=""):
        d = routes.DEFS.get(route.key)
        if d is None or route.batches.filter(status=Batch.Status.PENDING).exists() or \
                route.batches.filter(created_at__date=today).exists():
            continue
        rows = []
        for user, extra, dest, db_id in d.pick(now):
            if _eligible(user, d, now):
                rows.append((user, extra, dest, db_id))
            if len(rows) >= cap:
                break
        if not rows:
            continue
        with transaction.atomic():
            batch = Batch.objects.create(route=route)
            Message.objects.bulk_create([
                Message(batch=batch, user=u, route_key=d.key, phone=u.phone, dest=dest,
                        params={**extra, "NAME": routes.first_name(u), **({"_db": db_id} if db_id else {})},
                        status=Message.Status.CONTROL if _is_control(u, d.key, today) else Message.Status.PENDING)
                for u, extra, dest, db_id in rows])
        made.append(batch)
    return made


def link_for(code: str, stop: bool = False) -> str:
    return f"{settings.CANONICAL_URL}/r/{code}/" + ("stop/" if stop else "")


def sms_params(msg: Message) -> dict[str, str]:
    return {**{k: v for k, v in msg.params.items() if not k.startswith("_")},
            "LINK": link_for(msg.code), "STOP": link_for(msg.code, stop=True)}


def preview(msg: Message) -> str:
    d = routes.DEFS[msg.route_key]
    return routes.render(d.template, sms_params(msg))


@transaction.atomic
def approve(batch: Batch, admin_user, now=None) -> int:
    """تأیید مدیر: زمان بهینه‌ی هر کاربر را می‌گذارد (کنترل هم همان زمان را برای سنجش می‌گیرد)."""
    now = now or timezone.now()
    if batch.status != Batch.Status.PENDING:
        return 0
    n = 0
    for m in batch.messages.select_related("user").exclude(status=Message.Status.SKIPPED):
        m.send_at = timing.best_time(m.user, now, salt=zlib.crc32(batch.route.key.encode()) % 11)
        if m.status == Message.Status.PENDING:
            m.status = Message.Status.SCHEDULED
            n += 1
        m.save(update_fields=["send_at", "status"])
    batch.status, batch.approved_by, batch.approved_at = Batch.Status.APPROVED, admin_user, now
    batch.save(update_fields=["status", "approved_by", "approved_at"])
    return n


@transaction.atomic
def cancel(batch: Batch) -> None:
    if batch.status == Batch.Status.PENDING or batch.status == Batch.Status.APPROVED:
        batch.messages.filter(status__in=[Message.Status.PENDING, Message.Status.SCHEDULED, Message.Status.CONTROL]
                              ).update(status=Message.Status.SKIPPED, reason="دسته لغو شد")
        batch.status = Batch.Status.CANCELLED
        batch.save(update_fields=["status"])


def _skip(msg: Message, reason: str) -> None:
    msg.status, msg.reason = Message.Status.SKIPPED, reason
    msg.save(update_fields=["status", "reason"])


def send_due(now=None) -> dict:
    from accounts import sms

    now = now or timezone.now()
    out = {"sent": 0, "skipped": 0, "failed": 0}
    due = list(Message.objects.filter(status=Message.Status.SCHEDULED, send_at__lte=now)
               .select_related("user", "batch__route").order_by("send_at")[:PER_TICK])
    if not due:
        return out
    credit = sms.get_credit()
    if credit is not None and credit < len(due):
        out["failed"] = -1  # اعتبار کم؛ بعداً دوباره
        return out
    for m in due:
        route = m.batch.route
        if not route.enabled or not route.template_id or m.batch.status != Batch.Status.APPROVED:
            _skip(m, "مسیر خاموش یا لغو شده")
        elif not wants(m.user) or not m.user.is_active:
            _skip(m, "لغو یا غیرفعال")
        elif m.user.last_login and m.user.last_login > m.batch.created_at:
            _skip(m, "کاربر خودش برگشت")
        elif _capped(m.user, now):
            _skip(m, "سقف دفعات")
        elif not timing.in_window(now):
            m.send_at = timing.best_time(m.user, now)
            m.save(update_fields=["send_at"])
            continue
        else:
            try:
                sms.send_template(m.phone, route.template_id, sms_params(m))
            except sms.SMSError as exc:
                m.status, m.reason = Message.Status.FAILED, str(exc)[:200]
                m.save(update_fields=["status", "reason"])
                out["failed"] += 1
                continue
            m.status, m.sent_at = Message.Status.SENT, now
            m.save(update_fields=["status", "sent_at"])
            out["sent"] += 1
            continue
        out["skipped"] += 1
    return out


def measure(now=None) -> int:
    """بازگشت (ورود بعد از پیام) و پرداخت ۷ روز بعد از زمان ارسال را برای پیام‌ها و کنترل ثبت می‌کند."""
    from django.db.models import Sum

    from billing.models import Invoice

    now = now or timezone.now()
    n = 0
    open_ = Message.objects.filter(status__in=[Message.Status.SENT, Message.Status.CONTROL],
                                   send_at__gte=now - datetime.timedelta(days=WINDOW_DAYS + 1), send_at__lte=now
                                   ).select_related("user")
    for m in open_:
        end = m.send_at + datetime.timedelta(days=WINDOW_DAYS)
        ll = m.user.last_login
        if m.returned_at is None and ll and m.send_at <= ll <= end:
            m.returned_at = ll
            m.save(update_fields=["returned_at"])
            n += 1
        paid = Invoice.objects.filter(user=m.user, status=Invoice.Status.PAID, paid_at__gte=m.send_at,
                                      paid_at__lte=end).aggregate(s=Sum("amount_toman"))["s"] or 0
        if paid != m.paid_toman:
            m.paid_toman = paid
            m.save(update_fields=["paid_toman"])
    return n


def grant_gift(msg: Message) -> bool:
    """هدیه‌ی بازگشت در اولین کلیک (یک بار)؛ کنترل لینک ندارد. آزمایش پلاگین یا تمدید پایگاه."""
    route = Route.objects.filter(key=msg.route_key).first()
    if msg.gift_at or msg.status != Message.Status.SENT or route is None or route.gift_kind == Route.Gift.NONE:
        return False
    days = max(1, route.gift_days)
    if route.gift_kind == Route.Gift.TRIAL and route.gift_plugin:
        try:
            entitlements.grant(route.gift_plugin, "user", str(msg.user_id), source="trial", days=days,
                               note="هدیه‌ی بازگشت")
        except ValueError:
            log.exception("winback gift failed")
            return False
    elif route.gift_kind == Route.Gift.EXTEND and msg.params.get("_db"):
        from databases.models import UserDatabase

        db = UserDatabase.objects.filter(pk=msg.params["_db"], owner=msg.user).select_related("plan").first()
        if db is None or not db.is_live:
            return False
        db.extend(days)
        db.save(update_fields=["expires_at", "expiry_warned_at"])
    else:
        return False
    msg.gift_at = timezone.now()
    msg.save(update_fields=["gift_at"])
    return True


def results(key: str, now=None) -> dict:
    """نتیجه‌ی یک مسیر روی پیام‌هایی که پنجره‌ی ۷ روزه‌شان بسته شده؛ مقایسه با کنترل = اثر واقعی."""
    now = now or timezone.now()
    cut = now - datetime.timedelta(days=WINDOW_DAYS)
    base = Message.objects.filter(route_key=key)
    mature = base.filter(send_at__lte=cut)
    t, c = mature.filter(status=Message.Status.SENT), mature.filter(status=Message.Status.CONTROL)
    tn, cn = t.count(), c.count()
    tr, cr = t.filter(returned_at__isnull=False).count(), c.filter(returned_at__isnull=False).count()
    tp, cp = sum(t.values_list("paid_toman", flat=True)), sum(c.values_list("paid_toman", flat=True))
    rate_t, rate_c = (tr / tn if tn else None), (cr / cn if cn else None)
    return {
        "sent_total": base.filter(status=Message.Status.SENT).count(), "clicked": base.filter(clicked_at__isnull=False).count(),
        "mature_sent": tn, "mature_control": cn, "rate_sent": rate_t, "rate_control": rate_c,
        "uplift": (rate_t - rate_c) if rate_t is not None and rate_c is not None else None,
        "paid_sent": tp, "paid_control": cp,
        "extra_revenue": (tp / tn - cp / cn) * tn if tn and cn else None,
    }


def tick(now=None) -> str:
    """کار دوره‌ای worker: اندازه‌گیری همیشه؛ ساخت فهرست و ارسال فقط وقتی سوئیچ کلی روشن است."""
    now = now or timezone.now()
    measured = measure(now) if cache.add("winback:measure", 1, 600) else 0
    if not switch_on():
        return f"خاموش (اندازه‌گیری: {measured})"
    planned = 0
    if now.astimezone(timing.TZ).hour >= PLAN_HOUR and cache.add(f"winback:plan:{now:%Y%m%d}", 1, 3600 * 3):
        planned = len(plan_batches(now))
    sent = send_due(now)
    return f"فهرست تازه: {planned}، ارسال: {sent['sent']}، رد: {sent['skipped']}، ناموفق: {sent['failed']}، بازگشت: {measured}"


def pending_batches() -> int:
    return Batch.objects.filter(status=Batch.Status.PENDING).count()
