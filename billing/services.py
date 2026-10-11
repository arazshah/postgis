"""فاکتور، پرداخت و اعمال پلن."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from core.models import SiteSettings
from databases import services as db_services
from databases.models import Plan, UserDatabase
from databases.provisioner import ProvisionError

from .aban import FAILED_STATUSES, PAID_STATUSES, AbanClient, AbanError
from .models import Invoice, PlanVoucher

log = logging.getLogger(__name__)


class BillingError(Exception):
    pass


def paid_plans():
    return Plan.objects.filter(is_public=True, is_free=False, price_toman__gt=0).order_by("order", "price_toman")


def methods_available(conf: SiteSettings | None = None) -> list[str]:
    conf = conf or SiteSettings.get()
    out = []
    if conf.aban_ready:
        out.append(Invoice.Method.ABAN)
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
    db_services.logevent("invoice", f"فاکتور {inv.number}: {inv.title} – {inv.amount_toman} تومان",
                         user=user, database=database)
    return inv


# ---------------------------------------------------------------------- آبان گیت وی
def start_aban(inv: Invoice, request) -> str:
    if inv.status != Invoice.Status.PENDING or inv.is_expired_now:
        raise BillingError("این فاکتور دیگر قابل پرداخت نیست.")
    if inv.method == Invoice.Method.ABAN and inv.pay_url:
        return inv.pay_url
    callback = request.build_absolute_uri(reverse("billing:callback", args=[inv.number]))
    try:
        result = AbanClient().create(amount_rial=inv.amount_rial, order_id=inv.number, callback_url=callback,
                                     description=inv.title)
    except AbanError as exc:
        log.warning("aban create failed for %s: %s", inv.number, exc)
        db_services.logevent("payment", f"{inv.number}: {exc}", user=inv.user, database=inv.database, success=False)
        raise BillingError("اتصال به درگاه پرداخت ممکن نشد. چند دقیقه دیگر تلاش کنید یا از پرداخت با رسید استفاده کنید.") from exc
    inv.method = Invoice.Method.ABAN
    inv.provider_id = result.id
    inv.pay_url = result.pay_url
    inv.provider_status = result.status
    inv.save(update_fields=["method", "provider_id", "pay_url", "provider_status"])
    return inv.pay_url


def check_aban(inv: Invoice) -> Invoice:
    """وضعیت را مستقیم از آبان استعلام می‌کند؛ تنها راه تأیید پرداخت آبان."""
    if inv.method != Invoice.Method.ABAN or not inv.provider_id or inv.status == Invoice.Status.PAID:
        return inv
    try:
        result = AbanClient().get(inv.provider_id)
    except AbanError as exc:
        log.warning("aban status failed for %s: %s", inv.number, exc)
        return inv
    inv.provider_status = result.status
    inv.save(update_fields=["provider_status"])
    if result.status in PAID_STATUSES:
        if result.paid_rial is not None and result.paid_rial < inv.amount_rial:
            inv.note = (inv.note + f"\nمبلغ پرداخت‌شده ({result.paid_rial} ریال) کمتر از فاکتور است.").strip()
            inv.status = Invoice.Status.REVIEW
            inv.save(update_fields=["note", "status"])
            return inv
        mark_paid(inv)
    elif result.status in FAILED_STATUSES and inv.status == Invoice.Status.PENDING:
        inv.status = Invoice.Status.EXPIRED if "expire" in result.status else Invoice.Status.CANCELLED
        inv.save(update_fields=["status"])
    return inv


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
    db_services.logevent("payment", f"رسید فاکتور {inv.number} ثبت شد و منتظر تأیید است",
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
    db_services._notify(inv.user, "رسید پرداخت تأیید نشد",
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
    db_services.logevent("payment", f"فاکتور {locked.number} پرداخت شد ({locked.amount_toman} تومان)",
                         user=locked.user, database=locked.database)
    try:
        apply_invoice(locked)
    except (BillingError, ProvisionError, db_services.ServiceError) as exc:
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
    if inv.kind == Invoice.Kind.NEW:
        PlanVoucher.objects.get_or_create(invoice=inv, defaults={"user": inv.user, "plan": plan})
        body = f"پرداخت فاکتور {inv.number} تأیید شد. حالا می‌توانید پایگاه داده جدید با پلن {plan.name} بسازید."
    else:
        db = inv.database
        if db is None or db.status == UserDatabase.Status.DELETED:
            raise BillingError("پایگاه داده این فاکتور دیگر وجود ندارد.")
        p = db_services.provisioner_for(db.server)
        db.plan = plan
        db.extend(plan.duration_days)
        if db.status == UserDatabase.Status.EXPIRED:
            p.set_login(db.role_name, True)
            db.status = UserDatabase.Status.ACTIVE
        p.apply_limits(db.role_name, db_services.limits_for(plan))
        if db.status == UserDatabase.Status.READONLY and db.size_bytes <= plan.quota_bytes * 0.95:
            p.set_readonly(db.db_name, False)
            db.status = UserDatabase.Status.ACTIVE
        db.quota_warned_at = None
        db.save()
        db_services.logevent("plan", f"{inv.get_kind_display()} به پلن {plan.name} تا {db.expires_at:%Y-%m-%d}",
                             database=db)
        body = f"پرداخت فاکتور {inv.number} تأیید شد و پلن {plan.name} برای {db.label} فعال شد."
    inv.applied_at = timezone.now()
    inv.save(update_fields=["applied_at"])
    db_services._notify(inv.user, "پرداخت تأیید شد", body)


# ---------------------------------------------------------------------- نگهداری
def maintenance() -> dict:
    now = timezone.now()
    stats = {"checked": 0, "expired": 0}
    for inv in Invoice.objects.filter(status=Invoice.Status.PENDING, method=Invoice.Method.ABAN,
                                      created_at__gte=now - timedelta(days=2)).exclude(provider_id=""):
        check_aban(inv)
        stats["checked"] += 1
    stats["expired"] = Invoice.objects.filter(status=Invoice.Status.PENDING, expires_at__lt=now,
                                              method__in=["", Invoice.Method.MANUAL]).update(
        status=Invoice.Status.EXPIRED)
    # فاکتور آبانی که مهلتش گذشته و هنوز پرداخت نشده (یک روز فرصت برای تأیید دیرهنگام)
    stats["expired"] += Invoice.objects.filter(status=Invoice.Status.PENDING, method=Invoice.Method.ABAN,
                                               expires_at__lt=now - timedelta(days=1)).update(
        status=Invoice.Status.EXPIRED)
    return stats


def unused_vouchers(user):
    return PlanVoucher.objects.filter(user=user, used_by__isnull=True).select_related("plan")
