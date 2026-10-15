"""منطق کسب‌وکار: ساخت، حذف، تمدید، پایش حجم و انقضا."""
from __future__ import annotations

import logging
from datetime import timedelta

from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from .models import ActivityLog, DatabaseServer, Extension, Plan, UserDatabase
from .provisioner import Provisioner, ProvisionError, TenantLimits

log = logging.getLogger(__name__)



def conf():
    from core.models import SiteSettings

    return SiteSettings.get()


class ServiceError(Exception):
    pass


def provisioner_for(server: DatabaseServer) -> Provisioner:
    """نقطه قابل جایگزینی در تست‌ها."""
    return Provisioner.for_server(server)


def limits_for(plan: Plan) -> TenantLimits:
    return TenantLimits(
        connection_limit=plan.max_connections,
        statement_timeout_s=plan.statement_timeout_s,
        temp_file_limit_mb=plan.temp_file_limit_mb,
    )


def logevent(action, message="", *, user=None, database=None, success=True):
    ActivityLog.objects.create(user=user, database=database, action=action, message=message[:2000],
                               success=success)


def default_plan() -> Plan | None:
    return Plan.objects.filter(is_default=True).first() or Plan.objects.filter(is_free=True).first()


def pick_server() -> DatabaseServer | None:
    candidates = DatabaseServer.objects.filter(is_active=True).order_by("-is_default", "name")
    for server in candidates:
        if server.has_admin_password and server.has_capacity():
            return server
    return None


def user_can_create(user, ignore_limit: bool = False) -> tuple[bool, str]:
    c = conf()
    if not c.allow_new_databases:
        return False, "ساخت پایگاه داده جدید موقتاً غیرفعال است. کمی بعد دوباره سر بزنید."
    if ignore_limit:
        return True, ""
    count = user.databases.exclude(status__in=UserDatabase.GONE_STATUSES).count()
    if count >= c.max_databases_per_user:
        return False, f"هر کاربر حداکثر {c.max_databases_per_user} پایگاه داده می‌تواند داشته باشد."
    return True, ""


def create_database(user, label: str, password: str, extension_names: list[str], plan: Plan | None = None,
                    username: str | None = None, voucher=None) -> UserDatabase:
    if voucher is not None:
        if voucher.user_id != user.pk or voucher.used_by_id:
            raise ServiceError("این اعتبار قابل استفاده نیست.")
        plan = voucher.plan
    plan = plan or default_plan()
    if plan is None:
        raise ServiceError("هنوز هیچ پلنی تعریف نشده است. لطفاً بعداً تلاش کنید.")
    ok, reason = user_can_create(user, ignore_limit=voucher is not None)
    if not ok:
        raise ServiceError(reason)
    server = pick_server()
    if server is None:
        raise ServiceError("در حال حاضر ظرفیت آزاد روی سرورها وجود ندارد. لطفاً بعداً تلاش کنید.")

    allowed = {e.name: e for e in plan.extensions_qs()}
    chosen = [allowed[n] for n in extension_names if n in allowed]
    ident = UserDatabase.build_identifier(label)
    role = UserDatabase.build_identifier(username or f"{label}_user")
    if UserDatabase.objects.filter(db_name=ident).exists():
        raise ServiceError("این نام قبلاً استفاده شده است؛ نام دیگری انتخاب کنید.")
    if role == ident or UserDatabase.objects.filter(role_name=role).exists():
        raise ServiceError("این نام کاربری قبلاً استفاده شده است؛ نام دیگری انتخاب کنید.")

    with transaction.atomic():
        db = UserDatabase.objects.create(
            owner=user, server=server, plan=plan, label=label, db_name=ident, role_name=role,
            status=UserDatabase.Status.PENDING,
        )
    try:
        installed = provisioner_for(server).create_tenant(ident, role, password, [e.name for e in chosen],
                                                         limits_for(plan))
    except ProvisionError as exc:
        db.status = UserDatabase.Status.ERROR
        db.last_error = str(exc)
        db.save(update_fields=["status", "last_error"])
        logevent("create", str(exc), user=user, database=db, success=False)
        raise ServiceError("ساخت پایگاه داده با خطا مواجه شد. تیم پشتیبانی مطلع شد؛ لطفاً کمی بعد دوباره تلاش کنید.") from exc

    db.status = UserDatabase.Status.ACTIVE
    db.extend(plan.duration_days)
    db.last_error = ""
    db.save()
    db.extensions.set([e for e in chosen if e.name in installed])
    try:
        size = provisioner_for(server).database_sizes([ident]).get(ident)
        if size is not None:
            db.size_bytes, db.size_checked_at = size, timezone.now()
            db.save(update_fields=["size_bytes", "size_checked_at"])
    except ProvisionError:
        pass
    if voucher is not None:
        voucher.used_by = db
        voucher.used_at = timezone.now()
        voucher.save(update_fields=["used_by", "used_at"])
    logevent("create", f"ساخته شد روی {server.name} با افزونه‌های {', '.join(installed) or '-'}", user=user, database=db)
    return db


def reset_password(db: UserDatabase, password: str, actor=None):
    provisioner_for(db.server).set_password(db.role_name, password)
    logevent("password", "تغییر رمز پایگاه داده", user=actor, database=db)


def add_extension(db: UserDatabase, ext: Extension, actor=None):
    if not db.plan.extensions_qs().filter(pk=ext.pk).exists():
        raise ServiceError("این افزونه در پلن شما مجاز نیست.")
    provisioner_for(db.server).install_extension(db.db_name, ext.name)
    db.extensions.add(ext)
    logevent("extension", f"نصب افزونه {ext.name}", user=actor, database=db)


def delete_database(db: UserDatabase, actor=None, reason="درخواست کاربر"):
    try:
        provisioner_for(db.server).drop_tenant(db.db_name, db.role_name)
    except ProvisionError as exc:
        logevent("delete", str(exc), user=actor, database=db, success=False)
        raise ServiceError("حذف پایگاه داده روی سرور ناموفق بود.") from exc
    db.status = UserDatabase.Status.DELETED
    db.deleted_at = timezone.now()
    # آزاد کردن نام برای استفاده مجدد
    suffix = f"__del{db.pk}"
    db.db_name = db.db_name[: 63 - len(suffix)] + suffix
    db.role_name = db.role_name[: 63 - len(suffix)] + suffix
    db.browser_password_encrypted = ""
    db.save()
    _remove_published_files(db)
    logevent("delete", reason, user=actor, database=db)


def _remove_published_files(db: UserDatabase):
    """فایل‌های پروژه QGIS Server این پایگاه داده (شامل رمز نقش فقط‌خواندنی) پاک شوند."""
    from publish.models import Service
    from publish.ows import remove_service_files

    service = Service.objects.filter(database=db).first()
    if service:
        try:
            remove_service_files(service)
        except OSError:
            log.exception("remove ows files for %s", db.pk)
        service.ows_password_encrypted = ""
        service.save(update_fields=["ows_password_encrypted"])


def renew(db: UserDatabase, actor=None):
    if not db.plan.is_free:
        raise ServiceError("تمدید پلن پولی از طریق پرداخت انجام می‌شود.")
    if not db.can_renew_within(conf().renew_window_days):
        raise ServiceError("تمدید برای این پایگاه داده در حال حاضر ممکن نیست.")
    if db.status == UserDatabase.Status.EXPIRED:
        provisioner_for(db.server).set_login(db.role_name, True)
        db.status = UserDatabase.Status.ACTIVE
    db.extend()
    db.save()
    logevent("renew", f"تمدید تا {db.expires_at:%Y-%m-%d}", user=actor, database=db)


def set_status(db: UserDatabase, status: str, actor=None):
    """تغییر وضعیت از پنل ادمین (تعلیق/فعال‌سازی)."""
    p = provisioner_for(db.server)
    if status == UserDatabase.Status.SUSPENDED:
        p.set_login(db.role_name, False)
    elif status == UserDatabase.Status.ACTIVE:
        p.set_login(db.role_name, True)
        p.set_readonly(db.db_name, False)
    db.status = status
    db.save(update_fields=["status"])
    logevent("status", f"وضعیت: {db.get_status_display()}", user=actor, database=db)


def _notify(user, subject, body):
    """اطلاع‌رسانی: پیامک (اگر خط اطلاع‌رسانی تنظیم شده) و ایمیل (اگر کاربر ایمیل دارد)."""
    from accounts.sms import send_text

    try:
        send_text(user.phone, f"{conf().site_name}: {body}")
    except Exception:  # noqa: BLE001
        log.exception("sms notify failed")
    if user.email:
        try:
            send_mail(f"[{conf().site_name}] {subject}", body, None, [user.email], fail_silently=True)
        except Exception:  # noqa: BLE001
            log.exception("email failed")


def check_quotas() -> dict:
    """حجم همه دیتابیس‌های زنده را اندازه می‌گیرد و در صورت عبور از سقف فقط‌خواندنی می‌کند."""
    stats = {"checked": 0, "readonly": 0, "restored": 0, "errors": 0}
    now = timezone.now()
    for server in DatabaseServer.objects.all():
        dbs = list(server.databases.filter(status__in=UserDatabase.LIVE_STATUSES).select_related("plan", "owner"))
        if not dbs:
            continue
        p = provisioner_for(server)
        try:
            sizes = p.database_sizes([d.db_name for d in dbs])
        except ProvisionError as exc:
            stats["errors"] += 1
            logevent("quota", f"{server.name}: {exc}", success=False)
            continue
        for db in dbs:
            if db.db_name not in sizes:
                continue
            db.size_bytes = sizes[db.db_name]
            db.size_checked_at = now
            stats["checked"] += 1
            try:
                if db.status == UserDatabase.Status.ACTIVE and db.size_bytes > db.quota_bytes:
                    p.set_readonly(db.db_name, True)
                    db.status = UserDatabase.Status.READONLY
                    stats["readonly"] += 1
                    logevent("quota", "عبور از سقف حجم؛ فقط‌خواندنی شد", database=db)
                    _notify(db.owner, "حجم پایگاه داده پر شد",
                            f"پایگاه داده {db.label} به سقف حجم رسید و فقط‌خواندنی شد. "
                            "با حذف داده‌های اضافه (DROP یا TRUNCATE توسط پشتیبانی) یا ارتقای پلن دوباره فعال می‌شود.")
                elif db.status == UserDatabase.Status.READONLY and db.size_bytes <= db.quota_bytes * 0.95:
                    p.set_readonly(db.db_name, False)
                    db.status = UserDatabase.Status.ACTIVE
                    stats["restored"] += 1
                    logevent("quota", "حجم به زیر سقف برگشت؛ دوباره فعال شد", database=db)
                elif (db.status == UserDatabase.Status.ACTIVE and db.size_bytes > db.quota_bytes * 0.8
                      and not db.quota_warned_at):
                    db.quota_warned_at = now
                    _notify(db.owner, "هشدار حجم", f"بیش از ۸۰٪ حجم پایگاه داده {db.label} استفاده شده است.")
            except ProvisionError as exc:
                stats["errors"] += 1
                logevent("quota", str(exc), database=db, success=False)
            db.save(update_fields=["size_bytes", "size_checked_at", "status", "quota_warned_at"])
    return stats


def process_expiry() -> dict:
    """هشدار پیش از انقضا، تعلیق پس از انقضا، و حذف پس از مهلت."""
    now = timezone.now()
    c = conf()
    stats = {"warned": 0, "expired": 0, "deleted": 0, "errors": 0}

    for db in UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES, expires_at__isnull=False,
                                          expiry_warned_at__isnull=True,
                                          expires_at__lte=now + timedelta(days=c.expiry_warning_days),
                                          expires_at__gt=now).select_related("owner"):
        _notify(db.owner, "اعتبار پایگاه داده رو به پایان است",
                f"اعتبار {db.label} تا {db.days_left} روز دیگر تمام می‌شود. از داشبورد آن را رایگان تمدید کنید.")
        db.expiry_warned_at = now
        db.save(update_fields=["expiry_warned_at"])
        stats["warned"] += 1

    for db in UserDatabase.objects.filter(status__in=UserDatabase.LIVE_STATUSES, expires_at__lte=now).select_related(
            "server", "owner"):
        try:
            provisioner_for(db.server).set_login(db.role_name, False)
            db.status = UserDatabase.Status.EXPIRED
            db.save(update_fields=["status"])
            logevent("expire", "اعتبار تمام شد؛ ورود غیرفعال شد", database=db)
            _notify(db.owner, "اعتبار پایگاه داده تمام شد",
                    f"{db.label} منقضی شد. تا {c.expired_grace_days} روز فرصت تمدید دارید؛ پس از آن حذف می‌شود.")
            stats["expired"] += 1
        except ProvisionError as exc:
            stats["errors"] += 1
            logevent("expire", str(exc), database=db, success=False)

    cutoff = now - timedelta(days=c.expired_grace_days)
    for db in UserDatabase.objects.filter(status=UserDatabase.Status.EXPIRED, expires_at__lte=cutoff).select_related("server"):
        try:
            delete_database(db, reason="حذف خودکار پس از پایان مهلت تمدید")
            stats["deleted"] += 1
        except ServiceError:
            stats["errors"] += 1
    return stats


def harden_server(server: DatabaseServer) -> list[str]:
    done = provisioner_for(server).harden()
    logevent("server", f"ایمن‌سازی {server.name}: {', '.join(done)}")
    return done


def refresh_server(server: DatabaseServer, harden: bool = False):
    if harden:
        try:
            harden_server(server)
        except ProvisionError:
            pass  # پیام خطای اتصال در check گزارش می‌شود
    info = provisioner_for(server).check()
    server.last_check_at = timezone.now()
    server.last_check_ok = info.ok
    server.last_check_message = info.message
    if info.ok:
        server.server_version = info.server_version
        server.postgis_version = info.postgis_version
    server.save(update_fields=["last_check_at", "last_check_ok", "last_check_message", "server_version",
                               "postgis_version"])
    return info
