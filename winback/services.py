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
from .models import Batch, Coupon, Message, Preference, Route

log = logging.getLogger(__name__)
PLUGIN = "winback"
WEEK_CAP, MONTH_CAP, WINDOW_DAYS, PER_TICK, PLAN_HOUR = 1, 3, 7, 20, 5
FALLBACK_DAYS = 3  # «اول ایمیل، بعد پیامک»: صبر تا این روز برای کلیک/بازگشت


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


def effective_channel(route: Route, d: routes.RouteDef) -> str:
    """کانال تنظیم‌شده‌ی مسیر، محدود به کانال‌های مجاز تعریف آن (مسیر ایمیلی هرگز پیامک نمی‌شود)."""
    return route.channel if route.channel in d.channels else d.channels[0]


def _collect(d: routes.RouteDef, now, cap: int, route: Route | None = None) -> list:
    """(user, extra, dest, db_id, channel)؛ کاربرِ بدون کانال لازم این مسیر کنار گذاشته می‌شود."""
    wanted = effective_channel(route, d) if route else "sms"
    rows = []
    for user, extra, dest, db_id in d.pick(now):
        ch = routes.channel_for(user, wanted)
        if ch and _eligible(user, d, now):
            rows.append((user, extra, dest, db_id, ch))
        if len(rows) >= cap:
            break
    return rows


def _variant(user, key: str, route: Route) -> str:
    """نصف‌نصف و ثابت برای هر کاربر؛ بدون قالب B همیشه A."""
    d = routes.DEFS[key]
    ch = effective_channel(route, d)
    has_sms_b = ch in ("sms", "both", "email_sms") and route.template_id_b and d.variant_b
    has_email_b = ch != "sms" and (route.email_subject_b or d.email_subject_b)
    if not (has_sms_b or has_email_b):
        return "A"
    return "B" if hashlib.sha256(f"ab:{user.pk}:{key}".encode()).digest()[0] % 2 else "A"


def _make_batch(route: Route, d: routes.RouteDef, rows: list, today, fixed: dict | None = None) -> Batch:
    with transaction.atomic():
        batch = Batch.objects.create(route=route)
        Message.objects.bulk_create([
            Message(batch=batch, user=u, route_key=d.key, phone=(u.phone if routes.has_sms(u) else ""),
                    email=(u.email if routes.has_email(u) else ""), channel=ch, dest=dest, variant=_variant(u, d.key, route),
                    params={**extra, "NAME": routes.first_name(u), **(fixed or {}), **({"_db": db_id} if db_id else {})},
                    status=Message.Status.CONTROL if _is_control(u, d.key, today) else Message.Status.PENDING)
            for u, extra, dest, db_id, ch in rows])
    return batch


def ready(route: Route) -> bool:
    """مسیر برای ارسال آماده است؟ مسیر دارای پیامک قالب sms.ir می‌خواهد؛ مسیر فقط‌ایمیلی نه."""
    d = routes.DEFS.get(route.key)
    if d is None:
        return False
    return effective_channel(route, d) == "email" or bool(route.template_id)


def plan_batches(now=None) -> list[Batch]:
    """برای هر مسیر روشن (با قالب) حداکثر یک دسته‌ی منتظر تأیید در روز می‌سازد (مسیرهای فقط‌دستی را نه)."""
    now = now or timezone.now()
    sync_routes()
    cap = int(conf.get(PLUGIN, "max_batch") or 300)
    today = now.astimezone(timing.TZ).date()
    made = []
    for route in Route.objects.filter(enabled=True):
        d = routes.DEFS.get(route.key)
        if d is None or d.manual_only or not ready(route) or route.batches.filter(status=Batch.Status.PENDING).exists() or \
                route.batches.filter(created_at__date=today).exists():
            continue
        rows = _collect(d, now, cap, route)
        if rows:
            made.append(_make_batch(route, d, rows, today))
    return made


def manual_estimate(route: Route, fixed: dict, limit: int, now=None) -> dict:
    """پیش‌نمایش ارسال دستی بدون ساخت چیزی: تعداد، کنترل، بخش پیامک و نمونه."""
    now = now or timezone.now()
    d = routes.DEFS[route.key]
    rows = _collect(d, now, limit, route)
    today = now.astimezone(timing.TZ).date()
    control = sum(1 for r in rows if _is_control(r[0], d.key, today))
    demo = {"NAME": "علی", "LINK": "Ab3xK9aQ", "STOP": "Ab3xK9aQ", "DB": "پایگاه من",
            "DAYS": "45", "AMOUNT": "490,000"}
    sample = routes.render(d.text("A"), {**demo, **fixed})
    real = len(rows) - control
    sms_n = sum(1 for r in rows if r[4] in ("sms", "both", "email_sms") and not _is_control(r[0], d.key, today))
    email_n = sum(1 for r in rows if r[4] != "sms" and not _is_control(r[0], d.key, today))
    subject = email_subject(d, route, "A", {**demo, **fixed})
    return {"rows": rows, "count": len(rows), "control": control, "real": real,
            "segments": sms_n * routes.segments(sample) if sample else 0, "sample": sample,
            "sms_n": sms_n, "email_n": email_n, "email_subject": subject}


def manual_send(route: Route, fixed: dict, limit: int, admin_user, now=None) -> tuple[Batch | None, int]:
    """ساخت و تأیید یک‌جای دسته‌ی دستی (فراخوان باید stepup را گذرانده باشد). همان قاعده‌های رضایت/سقف/کنترل/زمان."""
    now = now or timezone.now()
    d = routes.DEFS[route.key]
    rows = _collect(d, now, limit, route)
    if not rows:
        return None, 0
    batch = _make_batch(route, d, rows, now.astimezone(timing.TZ).date(), fixed)
    return batch, approve(batch, admin_user, now)


def link_for(code: str, stop: bool = False) -> str:
    return f"{settings.CANONICAL_URL}/r/{code}/" + ("stop/" if stop else "")


def sms_params(msg: Message) -> dict[str, str]:
    """فقط پارامترهایی که در متن همان نسخه‌ی قالب هست (قالب sms.ir پارامتر اضافه را ممکن است نپذیرد).

    LINK و STOP فقط «کد کوتاه» انتهای لینک‌اند؛ دامنه و مسیر ثابتِ داخل متن قالب است (شرط sms.ir).
    """
    allp = {**{k: v for k, v in msg.params.items() if not k.startswith("_")}, "LINK": msg.code, "STOP": msg.code}
    text = routes.DEFS[msg.route_key].text(sms_variant(msg))
    return {k: v for k, v in allp.items() if f"#{k}#" in text}


def sms_variant(msg: Message, route: Route | None = None) -> str:
    """B فقط وقتی قالب B واقعاً ساخته شده (آزمون A/B ایمیل نباید پیامک را به متن بی‌قالب ببرد)."""
    route = route or Route.objects.filter(key=msg.route_key).first()
    return "B" if msg.variant == "B" and route is not None and route.template_id_b else "A"


def email_subject(d: routes.RouteDef, route: Route, variant: str, params: dict) -> str:
    raw = (route.email_subject_b or d.email_subject_b) if variant == "B" else ""
    raw = raw or route.email_subject or d.email_subject
    return " ".join(routes.render(raw, params).split())[:150]


def preview(msg: Message) -> str:
    d = routes.DEFS[msg.route_key]
    if msg.channel == "email" or not d.template:
        return f"[ایمیل] {email_subject(d, Route.objects.get(key=msg.route_key), msg.variant, {**msg.params, 'LINK': msg.code, 'STOP': msg.code})}"
    return routes.render(d.text(sms_variant(msg)), sms_params(msg))


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


def _email_cap_left(now) -> int:
    """سقف روزانه‌ی ایمیل بازاریابی (جدا از سقف کل سرور) تا بازاریابی ایمیل‌های امنیتی و رسید را گرسنه نکند."""
    cap = int(conf.get(PLUGIN, "email_daily_cap") or 0)
    used = Message.objects.filter(sent_at__gte=now - datetime.timedelta(hours=24), via__contains="email").count()
    return max(cap - used, 0)


def _email_headers(msg: Message) -> dict:
    url = f"{settings.CANONICAL_URL.rstrip('/')}/r/{msg.code}/oneclick/"
    return {"List-Unsubscribe": f"<{url}>", "List-Unsubscribe-Post": "List-Unsubscribe=One-Click"}


def send_email(msg: Message, d: routes.RouteDef, route: Route) -> str:
    """ایمیل بازاریابی را در صف kernel.mail می‌گذارد. برمی‌گرداند "" در موفقیت، وگرنه دلیل (فارسی/کد کوتاه)."""
    from kernel import mail

    base = settings.CANONICAL_URL.rstrip("/")
    params = {**{k: v for k, v in msg.params.items() if not k.startswith("_")}, "LINK": msg.code, "STOP": msg.code}
    ctx = {
        "subject": email_subject(d, route, msg.variant, params),
        "paragraphs": [routes.render(line, params) for line in d.email_body.splitlines() if line.strip()],
        "url": f"{base}/r/{msg.code}/?c=e", "label": d.email_cta,
        "unsubscribe_url": f"{base}/r/{msg.code}/stop/",
        "reason": "این ایمیل را چون در ژئوپایگاه حساب دارید دریافت کرده‌اید.",
    }
    row = mail.send("winback", user=msg.user, to=msg.email, context=ctx, key=f"wb:{msg.code}", headers=_email_headers(msg))
    if row is None:
        return "ایمیل در صف نرفت"
    if row.status == "skipped":
        return {"unverified": "ایمیل تأییدنشده", "no-consent": "رضایت ندارد", "pref-off": "ایمیل خاموش"}.get(row.error, row.error)
    return ""


def send_due(now=None) -> dict:
    from accounts import sms

    now = now or timezone.now()
    out = {"sent": 0, "skipped": 0, "failed": 0}
    due = list(Message.objects.filter(status=Message.Status.SCHEDULED, send_at__lte=now)
               .select_related("user", "batch__route").order_by("send_at")[:PER_TICK])
    if not due:
        return out
    sms_due = sum(1 for m in due if m.channel in ("sms", "both"))
    credit = sms.get_credit() if sms_due else None
    sms_ok = credit is None or credit >= sms_due
    email_left = _email_cap_left(now)
    for m in due:
        route = m.batch.route
        d = routes.DEFS.get(m.route_key)
        tid = route.template_id_b if sms_variant(m, route) == "B" else route.template_id
        sms_leg = m.channel in ("sms", "both") and bool(tid) and bool(m.phone)
        email_leg = m.channel in ("email", "both", "email_sms") and bool(m.email)
        if d is None or not route.enabled or m.batch.status != Batch.Status.APPROVED:
            _skip(m, "مسیر خاموش یا لغو شده")
        elif not (sms_leg or email_leg):
            _skip(m, "قالب پیامک یا ایمیل کاربر موجود نیست")
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
            via, errors = [], []
            if email_leg:
                if email_left <= 0:
                    errors.append("سقف روزانه‌ی ایمیل بازاریابی")
                    if not sms_leg:
                        continue  # فردا دوباره؛ زمان‌بندی همان می‌ماند
                else:
                    why = send_email(m, d, route)
                    if why:
                        errors.append(why)
                    else:
                        via.append("email")
                        email_left -= 1
            if sms_leg:
                if not sms_ok:
                    if not via:
                        continue  # اعتبار پیامک کم است؛ بعداً دوباره
                else:
                    try:
                        sms.send_template(m.phone, tid, sms_params(m))
                        via.append("sms")
                    except sms.SMSError as exc:
                        errors.append(str(exc))
            if not via:
                m.status, m.reason = Message.Status.FAILED, "؛ ".join(errors)[:200]
                m.save(update_fields=["status", "reason"])
                out["failed"] += 1
                continue
            m.status, m.sent_at, m.via = Message.Status.SENT, now, "+".join(via)
            if m.channel == "email_sms" and "email" in via and m.phone and route.template_id:
                m.sms_fallback_at = now + datetime.timedelta(days=FALLBACK_DAYS)
            m.save(update_fields=["status", "sent_at", "via", "sms_fallback_at"])
            out["sent"] += 1
            continue
        out["skipped"] += 1
    return out


def send_fallbacks(now=None) -> int:
    """«اول ایمیل، بعد پیامک»: اگر تا ۳ روز نه کلیک شد نه کاربر برگشت، همان پیام یک‌بار با پیامک می‌رود (هزینه فقط برای بی‌پاسخ‌ها).

    رضایت و پنجره‌ی زمانی دوباره سنجیده می‌شود؛ سقف دفعات نه (همین پیام خودش در سقف شمرده شده است).
    """
    from accounts import sms

    now = now or timezone.now()
    n = 0
    due = list(Message.objects.filter(status=Message.Status.SENT, sms_fallback_at__isnull=False, sms_fallback_at__lte=now)
               .select_related("user")[:PER_TICK])
    credit = sms.get_credit() if due else None
    left = None if credit is None else int(credit)
    for m in due:
        route = Route.objects.filter(key=m.route_key).first()
        done = (m.clicked_at or m.returned_at or not wants(m.user) or not m.user.is_active or route is None
                or not route.enabled or not route.template_id or not m.phone
                or (m.user.last_login and m.sent_at and m.user.last_login > m.sent_at))
        if done:
            m.sms_fallback_at = None
            m.save(update_fields=["sms_fallback_at"])
            continue
        if not timing.in_window(now) or (left is not None and left < 1):
            continue
        tid = route.template_id_b if sms_variant(m, route) == "B" else route.template_id
        try:
            sms.send_template(m.phone, tid, sms_params(m))
        except sms.SMSError as exc:
            m.reason = str(exc)[:200]
            m.sms_fallback_at = None
            m.save(update_fields=["reason", "sms_fallback_at"])
            continue
        m.via, m.sms_fallback_at = f"{m.via}+sms", None
        m.save(update_fields=["via", "sms_fallback_at"])
        n += 1
        if left is not None:
            left -= 1
    return n


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


def give(kind: str, user, *, plugin: str = "", days: int = 7, percent: int = 20, db_id=None, message=None) -> bool:
    """پاداش به کاربر (مشترک بین هدیه‌ی پیامک و پاداش دعوت): آزمایش پلاگین، تمدید پایگاه یا تخفیف مهلت‌دار."""
    days = max(1, days)
    if kind == Route.Gift.TRIAL and plugin:
        try:
            entitlements.grant(plugin, "user", str(user.pk), source="trial", days=days, note="هدیه")
        except ValueError:
            log.exception("winback gift failed")
            return False
        return True
    if kind == Route.Gift.COUPON:
        hours = int(conf.get(PLUGIN, "coupon_hours") or 72)
        fields = {"user": user, "percent": min(max(percent, 1), 90),
                  "expires_at": timezone.now() + datetime.timedelta(hours=hours)}
        if message is not None:
            Coupon.objects.get_or_create(message=message, defaults=fields)
        else:
            Coupon.objects.create(**fields)
        return True
    if kind == Route.Gift.EXTEND:
        from databases.models import UserDatabase

        qs = UserDatabase.objects.filter(owner=user, status__in=UserDatabase.LIVE_STATUSES).select_related("plan")
        db = qs.filter(pk=db_id).first() if db_id else qs.order_by("-created_at").first()
        if db is None or db.expires_at is None:  # پایگاه بدون انقضا تمدید نمی‌خواهد (و نباید تاریخ انقضا بگیرد)
            return False
        db.extend(days)
        db.save(update_fields=["expires_at", "expiry_warned_at", "expiry_stage"])
        return True
    return False


def grant_gift(msg: Message) -> bool:
    """هدیه‌ی بازگشت در اولین کلیک (یک بار)؛ کنترل لینک ندارد."""
    route = Route.objects.filter(key=msg.route_key).first()
    if msg.gift_at or msg.status != Message.Status.SENT or route is None or route.gift_kind == Route.Gift.NONE:
        return False
    if not give(route.gift_kind, msg.user, plugin=route.gift_plugin, days=route.gift_days, percent=route.gift_percent,
                db_id=msg.params.get("_db"), message=msg):
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
    from . import referrals

    rewarded = referrals.reward_due(now)
    if not switch_on():
        return f"خاموش (اندازه‌گیری: {measured}، پاداش دعوت: {rewarded})"
    planned = 0
    if now.astimezone(timing.TZ).hour >= PLAN_HOUR and cache.add(f"winback:plan:{now:%Y%m%d}", 1, 3600 * 3):
        planned = len(plan_batches(now))
    sent = send_due(now)
    sent["fallback"] = send_fallbacks(now)
    return f"فهرست تازه: {planned}، ارسال: {sent['sent']} (پیامک پس از ایمیل: {sent['fallback']})، رد: {sent['skipped']}، ناموفق: {sent['failed']}، بازگشت: {measured}"


def pending_batches() -> int:
    return Batch.objects.filter(status=Batch.Status.PENDING).count()


def ab_results(key: str, now=None) -> dict | None:
    """مقایسه‌ی A و B روی پیام‌های رسیده‌ی ۷ روزه: نرخ بازگشت هر نسخه و برنده (آزمون دو نسبت، حداقل ۳۰ نفر در هر نسخه)."""
    import math

    now = now or timezone.now()
    base = Message.objects.filter(route_key=key, status=Message.Status.SENT,
                                  send_at__lte=now - datetime.timedelta(days=WINDOW_DAYS))
    out = {}
    for v in ("A", "B"):
        q = base.filter(variant=v)
        n = q.count()
        out[v] = {"n": n, "returned": q.filter(returned_at__isnull=False).count(),
                  "clicked": q.filter(clicked_at__isnull=False).count()}
    if not out["B"]["n"]:
        return None
    a, b = out["A"], out["B"]
    out["winner"] = ""
    if a["n"] >= 30 and b["n"] >= 30:
        pa, pb = a["returned"] / a["n"], b["returned"] / b["n"]
        p = (a["returned"] + b["returned"]) / (a["n"] + b["n"])
        se = math.sqrt(p * (1 - p) * (1 / a["n"] + 1 / b["n"])) or 1
        z = (pb - pa) / se
        out["z"] = z
        if abs(z) >= 1.96:
            out["winner"] = "B" if z > 0 else "A"
    return out
