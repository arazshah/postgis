"""فاکتور، پرداخت و اعمال پلن."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import SiteSettings
from databases.models import Plan, UserDatabase
from kernel import entitlements, workspace

from .gateways import GatewayError, get_gateway
from .models import Invoice, PlanVoucher, PluginAddon

log = logging.getLogger(__name__)


class BillingError(Exception):
    pass


def paid_plans():
    return Plan.objects.filter(is_public=True, is_free=False, price_toman__gt=0).order_by("order", "price_toman")


def methods_available(conf: SiteSettings | None = None) -> list[str]:
    conf = conf or SiteSettings.get()
    out = []
    if conf.gateway_ready:
        out.append(Invoice.Method.GATEWAY)
    if conf.manual_ready:
        out.append(Invoice.Method.MANUAL)
    return out


# ---------------------------------------------------------------------- ساخت فاکتور
def create_invoice(user, kind: str, plan: Plan, database: UserDatabase | None = None) -> Invoice:
    conf = SiteSettings.get()
    if not conf.pay_enabled or not methods_available(conf):
        raise BillingError("فروش پلن‌های پولی فعلاً فعال نیست.")
    if plan.is_free or plan.price_toman <= 0 or not plan.is_public:
        raise BillingError("این پلن قابل خرید نیست.")
    if kind in (Invoice.Kind.UPGRADE, Invoice.Kind.RENEW):
        if database is None or database.owner_id != user.pk or database.status == UserDatabase.Status.DELETED:
            raise BillingError("پایگاه داده نامعتبر است.")
        if database.status == UserDatabase.Status.SUSPENDED:
            raise BillingError("این پایگاه داده معلق است؛ با پشتیبانی تماس بگیرید.")
        if kind == Invoice.Kind.UPGRADE and database.plan_id == plan.pk:
            kind = Invoice.Kind.RENEW
    elif kind == Invoice.Kind.NEW:
        database = None
    else:
        raise BillingError("نوع فاکتور نامعتبر است.")

    existing = Invoice.objects.filter(user=user, kind=kind, plan=plan, database=database,
                                      status=Invoice.Status.PENDING, expires_at__gt=timezone.now()).first()
    if existing:
        return existing
    inv = Invoice.objects.create(
        user=user, kind=kind, plan=plan, database=database, amount_toman=plan.price_toman,
        expires_at=timezone.now() + timedelta(minutes=conf.invoice_ttl_minutes))
    workspace.log_event("invoice", f"فاکتور {inv.number}: {inv.title} – {inv.amount_toman} تومان",
                         user=user, database=database)
    return inv


def public_addons():
    """افزونه‌های قابل فروش: فقط آن‌هایی که پلاگینشان نصب و غیرسیستمی است."""
    from kernel.plugins import registry

    return [a for a in PluginAddon.objects.filter(is_public=True, price_toman__gt=0)
            if (p := registry.plugins.get(a.plugin_id)) and p.kind != "system"]


def create_addon_invoice(user, addon: PluginAddon, database: UserDatabase | None = None) -> Invoice:
    conf = SiteSettings.get()
    if not conf.pay_enabled or not methods_available(conf):
        raise BillingError("فروش فعلاً فعال نیست.")
    if addon not in public_addons():
        raise BillingError("این افزونه قابل خرید نیست.")
    if addon.scope == PluginAddon.Scope.WORKSPACE:
        if database is None or database.owner_id != user.pk or database.status == UserDatabase.Status.DELETED:
            raise BillingError("برای این افزونه یک پایگاه داده‌ی خودتان را انتخاب کنید.")
    else:
        database = None
    existing = Invoice.objects.filter(user=user, kind=Invoice.Kind.ADDON, addon=addon, database=database,
                                      status=Invoice.Status.PENDING, expires_at__gt=timezone.now()).first()
    if existing:
        return existing
    inv = Invoice.objects.create(
        user=user, kind=Invoice.Kind.ADDON, plan=None, addon=addon, database=database, amount_toman=addon.price_toman,
        expires_at=timezone.now() + timedelta(minutes=conf.invoice_ttl_minutes))
    workspace.log_event("invoice", f"فاکتور {inv.number}: {inv.title} – {inv.amount_toman} تومان", user=user, database=database)
    return inv


# ---------------------------------------------------------------------- درگاه پرداخت
def _callback_url(inv: Invoice, request) -> str:
    return f"{settings.CANONICAL_URL.rstrip('/')}{reverse('billing:callback', args=[inv.number])}"


def start_gateway(inv: Invoice, request) -> str:
    """یک درخواست پرداخت تازه می‌سازد و لینک درگاه را برمی‌گرداند."""
    if inv.status != Invoice.Status.PENDING or inv.is_expired_now:
        raise BillingError("این فاکتور دیگر قابل پرداخت نیست.")
    conf = SiteSettings.get()
    try:
        gw = get_gateway(conf)
        result = gw.request(amount_rial=inv.amount_rial, callback_url=_callback_url(inv, request),
                            description=f"{conf.site_name} – فاکتور {inv.number}: {inv.title}",
                            order_id=inv.number, mobile=inv.user.phone or "", email=inv.user.email or "")
    except GatewayError as exc:
        log.warning("gateway request failed for %s: %s", inv.number, exc)
        workspace.log_event("payment", f"{inv.number}: {exc}"[:500], user=inv.user, database=inv.database,
                             success=False)
        msg = "اتصال به درگاه پرداخت ممکن نشد. چند دقیقه دیگر تلاش کنید"
        msg += " یا از روش کارت به کارت استفاده کنید." if conf.manual_ready else "."
        raise BillingError(f"{msg} ({exc})" if exc.code not in ("", "network") else msg) from exc
    inv.method = Invoice.Method.GATEWAY
    inv.gateway = gw.name
    inv.provider_id = result.token
    inv.pay_url = result.pay_url
    inv.provider_status = ""
    inv.save(update_fields=["method", "gateway", "provider_id", "pay_url", "provider_status"])
    return result.pay_url


def verify_gateway(inv: Invoice, token: str | None = None) -> Invoice:
    """
    تأیید سمت سرور؛ تنها راه پرداخت‌شده شدن فاکتور درگاهی.
    token فقط وقتی پذیرفته می‌شود که همان شناسه ثبت‌شده برای این فاکتور باشد.
    """
    if inv.method != Invoice.Method.GATEWAY or not inv.provider_id or inv.status == Invoice.Status.PAID:
        return inv
    if token is not None and str(token) != inv.provider_id:
        log.warning("callback token mismatch for %s", inv.number)
        return inv
    try:
        gw = get_gateway(name=inv.gateway or None)
        res = gw.verify(inv.provider_id, inv.amount_rial)
    except GatewayError as exc:
        log.warning("gateway verify failed for %s: %s", inv.number, exc)
        inv.provider_status = str(exc)[:200]
        inv.save(update_fields=["provider_status"])
        return inv
    if not res.paid:
        inv.provider_status = res.message[:200]
        inv.save(update_fields=["provider_status"])
        return inv
    inv.gateway_ref = res.ref_id
    inv.payer_card_last4 = res.card
    inv.provider_status = "تأیید شد" + (" (قبلاً)" if res.already else "")
    inv.save(update_fields=["gateway_ref", "payer_card_last4", "provider_status"])
    mark_paid(inv)
    inv.refresh_from_db()
    return inv


def cancel_invoice(inv: Invoice) -> None:
    if inv.status != Invoice.Status.PENDING:
        return
    inv.status = Invoice.Status.CANCELLED
    inv.save(update_fields=["status"])


# ---------------------------------------------------------------------- پرداخت دستی
def submit_receipt(inv: Invoice, *, receipt, last4: str, tracking: str, paid_time: str) -> Invoice:
    if inv.status not in (Invoice.Status.PENDING, Invoice.Status.REJECTED):
        raise BillingError("برای این فاکتور نمی‌توان رسید ثبت کرد.")
    inv.method = Invoice.Method.MANUAL
    inv.receipt = receipt
    inv.payer_card_last4 = last4
    inv.tracking_code = tracking
    inv.paid_at_claimed = paid_time
    inv.status = Invoice.Status.REVIEW
    inv.save()
    workspace.log_event("payment", f"رسید فاکتور {inv.number} ثبت شد و منتظر تأیید است",
                         user=inv.user, database=inv.database)
    return inv


def reject(inv: Invoice, actor, reason: str = ""):
    if inv.status == Invoice.Status.PAID:
        raise BillingError("فاکتور پرداخت‌شده را نمی‌توان رد کرد.")
    inv.status = Invoice.Status.REJECTED
    inv.reviewed_by = actor
    if reason:
        inv.note = (inv.note + "\n" + reason).strip()
    inv.save(update_fields=["status", "reviewed_by", "note"])
    workspace.notify_user(inv.user, "رسید پرداخت تأیید نشد",
                        f"رسید فاکتور {inv.number} تأیید نشد. {reason} برای پیگیری با پشتیبانی تماس بگیرید.")


# ---------------------------------------------------------------------- تأیید و اعمال
def mark_paid(inv: Invoice, actor=None) -> Invoice:
    """یک‌بار و فقط یک‌بار؛ تکرار آن بی‌اثر است."""
    with transaction.atomic():
        locked = Invoice.objects.select_for_update().get(pk=inv.pk)
        if locked.status == Invoice.Status.PAID:
            return locked
        locked.status = Invoice.Status.PAID
        locked.paid_at = timezone.now()
        if actor is not None:
            locked.reviewed_by = actor
        locked.save(update_fields=["status", "paid_at", "reviewed_by"])
    workspace.log_event("payment", f"فاکتور {locked.number} پرداخت شد ({locked.amount_toman} تومان)",
                         user=locked.user, database=locked.database)
    try:
        apply_invoice(locked)
    except (BillingError, workspace.WorkspaceError) as exc:
        locked.note = (locked.note + f"\nاعمال خودکار ناموفق: {exc}").strip()
        locked.save(update_fields=["note"])
        log.exception("apply invoice %s failed", locked.number)
    return locked


def apply_invoice(inv: Invoice):
    if inv.status != Invoice.Status.PAID:
        raise BillingError("فاکتور پرداخت نشده است.")
    if inv.applied_at:
        return
    plan = inv.plan
    if inv.kind == Invoice.Kind.ADDON:
        addon = inv.addon
        if addon is None:
            raise BillingError("افزونه‌ی این فاکتور دیگر وجود ندارد.")
        if addon.scope == PluginAddon.Scope.WORKSPACE:
            if inv.database is None or inv.database.status == UserDatabase.Status.DELETED:
                raise BillingError("پایگاه داده‌ی این فاکتور دیگر وجود ندارد.")
            kind, subject = "workspace", str(inv.database.pk)
        else:
            kind, subject = "user", str(inv.user.pk)
        try:
            entitlements.grant(addon.plugin_id, kind, subject, source="purchase", days=addon.duration_days,
                               limits=addon.limits, note=f"فاکتور {inv.number}")
        except ValueError as exc:
            raise BillingError(str(exc)) from exc
        workspace.log_event("plan", f"افزونه‌ی {addon.title} تا {addon.duration_days} روز فعال شد", user=inv.user, database=inv.database)
        body = f"پرداخت فاکتور {inv.number} تأیید شد و افزونه‌ی {addon.title} فعال شد."
    elif inv.kind == Invoice.Kind.NEW:
        PlanVoucher.objects.get_or_create(invoice=inv, defaults={"user": inv.user, "plan": plan})
        body = f"پرداخت فاکتور {inv.number} تأیید شد. حالا می‌توانید پایگاه داده جدید با پلن {plan.name} بسازید."
    else:
        db = inv.database
        if db is None or db.status == UserDatabase.Status.DELETED:
            raise BillingError("پایگاه داده این فاکتور دیگر وجود ندارد.")
        p = workspace.host(db)
        db.plan = plan
        db.extend(plan.duration_days)
        if db.status == UserDatabase.Status.EXPIRED:
            p.set_login(db.role_name, True)
            db.status = UserDatabase.Status.ACTIVE
        p.apply_limits(db.role_name, workspace.limits(plan))
        if db.status == UserDatabase.Status.READONLY and db.size_bytes <= plan.quota_bytes * 0.95:
            p.set_readonly(db.db_name, False)
            db.status = UserDatabase.Status.ACTIVE
        db.quota_warned_at = None
        db.save()
        workspace.log_event("plan", f"{inv.get_kind_display()} به پلن {plan.name} تا {db.expires_at:%Y-%m-%d}",
                             database=db)
        body = f"پرداخت فاکتور {inv.number} تأیید شد و پلن {plan.name} برای {db.label} فعال شد."
    inv.applied_at = timezone.now()
    inv.save(update_fields=["applied_at"])
    workspace.notify_user(inv.user, "پرداخت تأیید شد", body)


# ---------------------------------------------------------------------- نگهداری
def maintenance() -> dict:
    """پرداخت‌هایی که خریدار بعد از پرداخت به سایت برنگشته، این‌جا تأیید می‌شوند."""
    now = timezone.now()
    stats = {"checked": 0, "expired": 0}
    for inv in Invoice.objects.filter(status=Invoice.Status.PENDING, method=Invoice.Method.GATEWAY,
                                      created_at__gte=now - timedelta(days=1)).exclude(provider_id=""):
        verify_gateway(inv)
        stats["checked"] += 1
    stats["expired"] = Invoice.objects.filter(status=Invoice.Status.PENDING, expires_at__lt=now).update(
        status=Invoice.Status.EXPIRED)
    return stats


def unused_vouchers(user):
    return PlanVoucher.objects.filter(user=user, used_by__isnull=True).select_related("plan")


# ---------------------------------------------------------------------- بازارچه پلاگین (ADR-0008 مرحله‌ی ۶)
TRIAL_NOTE = "دوره‌ی آزمایشی"


def _subject(addon: PluginAddon, user, database: UserDatabase | None):
    """(نوع دارنده، شناسه) مجوز این افزونه برای این کاربر/پایگاه؛ BillingError اگر هدف درست نیست."""
    if addon.scope == PluginAddon.Scope.WORKSPACE:
        if database is None or database.owner_id != user.pk or database.status == UserDatabase.Status.DELETED:
            raise BillingError("برای این پلاگین یک پایگاه داده‌ی خودتان را انتخاب کنید.")
        return "workspace", str(database.pk)
    return "user", str(user.pk)


def addon_status(addon: PluginAddon, user, database: UserDatabase | None = None) -> dict:
    """وضعیت مجوز این پلاگین برای دارنده: {state: none|trial|active|expired، source، days_left، expires_at}."""
    from kernel.models import Entitlement

    try:
        kind, subject = _subject(addon, user, database)
    except BillingError:
        return {"state": "none", "source": "", "days_left": None, "expires_at": None}
    ent = Entitlement.objects.filter(state__plugin_id=addon.plugin_id, kind=kind, subject=subject).first()
    if ent is None:
        return {"state": "none", "source": "", "days_left": None, "expires_at": None}
    now = timezone.now()
    if ent.expires_at is None:
        return {"state": "active", "source": ent.source, "days_left": None, "expires_at": None}
    if ent.expires_at <= now:
        return {"state": "expired", "source": ent.source, "days_left": 0, "expires_at": ent.expires_at}
    left = max(1, (ent.expires_at - now).days + (1 if (ent.expires_at - now).seconds else 0))
    return {"state": "trial" if ent.source == "trial" else "active", "source": ent.source, "days_left": left, "expires_at": ent.expires_at}


def start_trial(user, addon: PluginAddon, database: UserDatabase | None = None):
    """دوره‌ی آزمایشی رایگان: **یک‌بار** برای هر (پلاگین، دارنده)؛ هر ردیف مجوز قبلی (حتی منقضی) مانع است."""
    from kernel.models import Entitlement

    if addon not in public_addons():
        raise BillingError("این پلاگین قابل دریافت نیست.")
    if addon.trial_days <= 0:
        raise BillingError("این پلاگین دوره‌ی آزمایشی ندارد.")
    kind, subject = _subject(addon, user, database)
    if Entitlement.objects.filter(state__plugin_id=addon.plugin_id, kind=kind, subject=subject).exists():
        raise BillingError("برای این پلاگین پیش‌تر مجوز (آزمایشی یا خرید) داشته‌اید؛ دوره‌ی آزمایشی فقط یک‌بار است.")
    try:
        ent = entitlements.grant(addon.plugin_id, kind, subject, source="trial", days=addon.trial_days, limits=addon.limits, note=TRIAL_NOTE)
    except ValueError as exc:
        raise BillingError(str(exc)) from exc
    workspace.log_event("plan", f"دوره‌ی آزمایشی {addon.title} ({addon.trial_days} روز) فعال شد", user=user, database=database)
    return ent


NEW_DAYS = 30
STATE_TEXT = {"active": "فعال", "trial": "آزمایشی", "expired": "منقضی شد؛ داده‌ها محفوظ است"}


def _row_text(r: dict) -> str:
    st, left = r["state"], r.get("days_left")
    if st == "active":
        return "فعال" + (f"؛ {left} روز مانده" if left is not None else "، بدون انقضا")
    if st == "trial":
        return f"آزمایشی؛ {left} روز مانده"
    return STATE_TEXT.get(st, "")


def _market_listing(plugin_id: str, addon: PluginAddon | None):
    """(نسخه‌ی فعال، آگهی): دسته، ویژگی‌ها و توضیح از افزونه‌ی فروشی، سپس آگهی ذخیره‌شده‌ی نسخه‌ی فعال، سپس ویترین پلاگین (kernel.showcase)."""
    from kernel import showcase
    from kernel.models import PluginRelease

    rel = PluginRelease.objects.filter(plugin_id=plugin_id, status=PluginRelease.Status.ACTIVE).first()
    acc = (rel.access or {}) if rel else {}
    lst = acc.get("listing") or {}
    sc = showcase.get(plugin_id)
    return rel, {"category": (addon.category if addon else "") or lst.get("category", "") or (sc.category if sc else ""),
                 "features": list((addon.features if addon else None) or lst.get("features") or (sc.features if sc else ())),
                 "details": (addon.details if addon else "") or lst.get("details", "") or (sc.details if sc else ""),
                 "summary": acc.get("summary", "") or (sc.tagline if sc else "")}, sc


def _market_item(plugin, addon: PluginAddon | None, user, dbs) -> dict:
    """کارت/صفحه‌ی یک پلاگین در بازارچه (رایگان، همراه سکو یا پولی) با وضعیت دارنده؛ برای مهمان هم کار می‌کند."""
    from django.templatetags.static import static
    from django.urls import reverse

    from kernel import showcase
    from kernel.market import CATEGORIES
    from kernel.models import PluginMedia

    rel, lst, sc = _market_listing(plugin.id, addon)
    media = [reverse("kernel:media", args=[m.token]) for m in PluginMedia.objects.filter(plugin_id=plugin.id)] or [static(f) for f in showcase.images(plugin.id)]
    rows, best = [], None
    if addon is not None and user is not None and user.is_authenticated:
        rows = [{"db": d, **addon_status(addon, user, d)} for d in dbs] if addon.scope == PluginAddon.Scope.WORKSPACE else [{"db": None, **addon_status(addon, user)}]
        for r in rows:
            r["text"] = _row_text(r) if r["state"] != "none" else ""
        rank = {"active": 0, "trial": 1, "expired": 2, "none": 3}
        best = min(rows, key=lambda r: rank[r["state"]], default=None)
        if best is not None and best["state"] == "none":
            best = None
    when = rel.activated_at or rel.uploaded_at if rel else None
    aud = dict(showcase.AUDIENCES)
    return {"id": plugin.id, "name": addon.title if addon else plugin.name, "summary": (addon.description if addon else "") or lst["summary"] or plugin.description,
            "category": lst["category"], "category_label": dict(CATEGORIES).get(lst["category"], ""), "features": lst["features"], "details": lst["details"],
            "images": media, "image": media[0] if media else "", "paid": addon is not None, "addon": addon, "price_toman": addon.price_toman if addon else 0,
            "included": plugin.kind == "system", "audiences": [(k, aud[k]) for k in (sc.audiences if sc else ()) if k in aud],
            "steps": list(sc.steps) if sc else [], "guides": list(sc.guides) if sc else [], "kb": list(sc.kb) if sc else [], "rail": sc.rail if sc else "",
            "video": sc.video if sc and showcase.has_video(sc.video) else "", "featured": sc.featured if sc else 0,
            "duration_days": addon.duration_days if addon else 0, "workspace": bool(addon and addon.scope == PluginAddon.Scope.WORKSPACE),
            "trial_days": addon.trial_days if addon else 0, "can_trial": bool(addon and addon.trial_days > 0), "version": rel.version if rel else plugin.version,
            "updated": when, "is_new": bool(when and (timezone.now() - when).days < NEW_DAYS), "rows": rows, "best": best,
            "status_text": (f"{best['db'].db_name} — " if best and best["db"] else "") + best["text"] if best else "", "owned": bool(best and best["state"] in ("active", "trial")),
            "sort_new": int(when.timestamp()) if when else 0}


def market_catalog(user) -> dict:
    """داده‌ی بازارچه: همه‌ی پلاگین‌های قابل‌عرضه (پولی با وضعیت دارنده، رایگان باز و همراه سکو)، دسته‌ها و مخاطب‌ها با شمار و پایگاه‌های کاربر."""
    from kernel import showcase
    from kernel.market import CATEGORIES
    from kernel.models import PluginState
    from kernel.plugins import registry

    dbs = list(user.databases.exclude(status__in=[UserDatabase.Status.DELETED, UserDatabase.Status.ERROR, UserDatabase.Status.PENDING]).select_related("plan")) if user.is_authenticated else []
    items, listed = [], set()
    for a in public_addons():
        listed.add(a.plugin_id)
        items.append(_market_item(registry.plugins[a.plugin_id], a, user, dbs))
    opened = set(PluginState.objects.filter(enabled=True, access=PluginState.Access.OPEN).values_list("plugin_id", flat=True))
    for pid, p in registry.plugins.items():
        if pid in listed or pid.startswith("x_"):
            continue
        if showcase.visible(pid) or (pid in opened and p.kind != "system"):
            items.append(_market_item(p, None, user, dbs))
    items.sort(key=lambda i: (i["featured"] or 99, not i["paid"], i["included"], i["name"]))
    for it in items:
        it["tags"] = " ".join(filter(None, ["paid" if it["paid"] else "free", "trial" if it["can_trial"] else "", "owned" if it["owned"] else "", "new" if it["is_new"] else "",
                                            f"cat-{it['category']}" if it["category"] else "", *[f"aud-{k}" for k, _l in it["audiences"]]]))
        it["q"] = " ".join([it["name"], it["summary"], it["category_label"], *it["features"], *[lbl for _k, lbl in it["audiences"]]])
    counts = {k: sum(1 for i in items if i["category"] == k) for k, _l in CATEGORIES}
    acount = {k: sum(1 for i in items if any(a == k for a, _l in i["audiences"])) for k, _l in showcase.AUDIENCES}
    return {"items": items, "dbs": dbs, "categories": [(k, label, counts[k]) for k, label in CATEGORIES if counts[k]],
            "audiences": [(k, label, acount[k]) for k, label in showcase.AUDIENCES if acount[k]],
            "n_paid": sum(1 for i in items if i["paid"]), "n_free": sum(1 for i in items if not i["paid"]), "n_trial": sum(1 for i in items if i["can_trial"]),
            "n_owned": sum(1 for i in items if i["owned"])}


def market_detail(user, plugin_id: str) -> dict | None:
    """جزئیات یک پلاگین بازارچه + نسخه‌های اخیر با یادداشت و پلاگین‌های هم‌دسته؛ None اگر در بازارچه نیست."""
    from kernel.models import PluginRelease

    data = market_catalog(user)
    item = next((i for i in data["items"] if i["id"] == plugin_id), None)
    if item is None:
        return None
    rels = PluginRelease.objects.filter(plugin_id=plugin_id, status__in=[PluginRelease.Status.ACTIVE, PluginRelease.Status.RETIRED]).order_by("-id")[:4]
    related = [i for i in data["items"] if i["id"] != plugin_id and i["category"] and i["category"] == item["category"]][:3]
    return {"item": item, "dbs": data["dbs"], "releases": [{"version": r.version, "at": r.activated_at or r.uploaded_at, "notes": r.notes, "active": r.status == PluginRelease.Status.ACTIVE} for r in rels],
            "related": related}


def market_items(user) -> dict:
    """سازگاری با فراخوان‌های قبلی: همان داده‌ی بازار."""
    return market_catalog(user)
