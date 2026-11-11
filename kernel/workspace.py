"""قرارداد «فضای کار» (پایگاه داده‌ی یک مشتری و اعضای آن): چه کسی با چه سطحی به کدام فضای کار دسترسی دارد.

بخش‌های دیگر فقط از اینجا می‌پرسند و `databases.team` را نمی‌شناسند. پیاده‌سازی را پلاگین پایگاه داده با
`set_provider` ثبت می‌کند. مدل‌های فضای کار (پایگاه، پلن، عضو) همچنان در اپ `databases` می‌مانند و
هدف کلید خارجی بخش‌های دیگرند؛ این ماژول فقط رفتار را قرارداد می‌کند.
"""
from __future__ import annotations

VIEWER, EDITOR, OWNER = 1, 2, 3
LEVELS = {"viewer": VIEWER, "editor": EDITOR, "owner": OWNER}


SESSION_PW_KEY = "gp_once_password_{}"  # کلید نشست برای نمایش یک‌باره‌ی رمز پایگاه تازه


class WorkspaceError(Exception):
    """خطای قابل نمایش در عملیات فضای کار (ساخت، تمدید، میزبانی)؛ پیام فارسی دارد."""


class HostingError(WorkspaceError):
    """خطای میزبانی: سرور PostGIS کاری را انجام نداد."""


class Provider:
    """پیاده‌ساز قرارداد دسترسی؛ پلاگین پایگاه داده آن را ثبت می‌کند."""

    def get(self, request, pk, need: str = "owner", qs=None):
        """فضای کار را برای کاربر درخواست برمی‌گرداند یا Http404 (بدون فاش‌کردن وجودش) اگر سطح کافی نیست.
        روی نتیجه `my_level`، `is_mine` و `can_edit` گذاشته می‌شود."""
        raise NotImplementedError

    def level(self, user, ws) -> int:
        """سطح کاربر در فضای کار: ۰ (بدون دسترسی)، مشاهده‌گر ۱، ویرایشگر ۲، مالک ۳."""
        raise NotImplementedError

    def shared_with(self, user):
        """فضای کارهایی که با کاربر به اشتراک گذاشته شده‌اند (QuerySet)."""
        raise NotImplementedError

    def peek(self, pk):
        """فضای کار بدون بررسی دسترسی (فقط برای دروازه‌ی مجوز پلاگین‌ها)؛ نبودن = None."""
        raise NotImplementedError

    def extra_role_name(self, ws, suffix: str) -> str:
        """نام نقش اضافه‌ی پایگاه (مثلاً برای GeoServer) برای این فضای کار."""
        raise NotImplementedError

    # ---- میزبانی و چرخه‌ی عمر
    def host(self, ws):
        """میزبان این فضای کار روی سرور PostGIS: عملیات مدیریتی مثل نصب افزونه، نقش‌ها، رمز، بازگردانی. خطا = HostingError."""
        raise NotImplementedError

    def role_name(self, ws, kind: str) -> str:
        """نام نقش کمکی فضای کار: browser (مرورگر و ابزارها) یا ows (فقط‌خواندنی WMS/WFS)."""
        raise NotImplementedError

    def limits(self, plan):
        """محدودیت‌های اجرایی پلن (اتصال، زمان کوئری، فایل موقت) برای اعمال روی نقش."""
        raise NotImplementedError

    def create_database(self, user, label: str, password: str, extensions: list[str], **kw):
        """ساخت فضای کار تازه برای کاربر (kw: plan، ignore_limit، …). خطا = WorkspaceError."""
        raise NotImplementedError

    def log_event(self, action: str, message: str = "", *, user=None, database=None, success: bool = True) -> None:
        raise NotImplementedError

    def notify_user(self, user, subject: str, body: str) -> None:
        """اطلاع‌رسانی به کاربر با پیامک و ایمیل (هر کدام که در دسترس باشد)."""
        raise NotImplementedError

    def plan_default(self, name: str, default=None):
        """مقدار پیش‌فرض یک ویژگی پلن وقتی فضای کار پلنی ندارد (پلن رایگان)."""
        raise NotImplementedError


_provider: Provider | None = None


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def provider() -> Provider:
    if _provider is None:
        raise WorkspaceError("ارائه‌دهنده‌ی دسترسی فضای کار ثبت نشده است.")
    return _provider


def get(request, pk, need: str = "owner", qs=None):
    return provider().get(request, pk, need, qs)


def level(user, ws) -> int:
    return provider().level(user, ws)


def shared_with(user):
    return provider().shared_with(user)


def peek(pk):
    return provider().peek(pk)


def extra_role_name(ws, suffix: str) -> str:
    return provider().extra_role_name(ws, suffix)


def host(ws):
    return provider().host(ws)


def role_name(ws, kind: str) -> str:
    return provider().role_name(ws, kind)


def limits(plan):
    return provider().limits(plan)


def create_database(user, label: str, password: str, extensions: list[str], **kw):
    return provider().create_database(user, label, password, extensions, **kw)


def log_event(action: str, message: str = "", *, user=None, database=None, success: bool = True) -> None:
    provider().log_event(action, message, user=user, database=database, success=success)


def notify_user(user, subject: str, body: str) -> None:
    provider().notify_user(user, subject, body)


def plan_default(name: str, default=None):
    return provider().plan_default(name, default)


def open_catalog(request, pk, need: str = "viewer"):
    """فضای کار + کاتالوگ داده‌اش برای نما: اگر فضای کار فعال نیست، پیام فارسی می‌گذارد و کاتالوگ None است."""
    from django.contrib import messages

    from . import tenantdb

    ws = get(request, pk, need)
    if not ws.is_live:
        messages.error(request, "مرورگر فقط برای پایگاه داده فعال در دسترس است.")
        return ws, None
    return ws, tenantdb.catalog(ws)
