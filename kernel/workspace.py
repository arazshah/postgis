"""قرارداد «فضای کار» (پایگاه داده‌ی یک مشتری و اعضای آن): چه کسی با چه سطحی به کدام فضای کار دسترسی دارد.

بخش‌های دیگر فقط از اینجا می‌پرسند و `databases.team` را نمی‌شناسند. پیاده‌سازی را پلاگین پایگاه داده با
`set_provider` ثبت می‌کند. مدل‌های فضای کار (پایگاه، پلن، عضو) همچنان در اپ `databases` می‌مانند و
هدف کلید خارجی بخش‌های دیگرند؛ این ماژول فقط رفتار را قرارداد می‌کند.
"""
from __future__ import annotations

VIEWER, EDITOR, OWNER = 1, 2, 3
LEVELS = {"viewer": VIEWER, "editor": EDITOR, "owner": OWNER}


class WorkspaceError(Exception):
    pass


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

    def extra_role_name(self, ws, suffix: str) -> str:
        """نام نقش اضافه‌ی پایگاه (مثلاً برای GeoServer) برای این فضای کار."""
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


def extra_role_name(ws, suffix: str) -> str:
    return provider().extra_role_name(ws, suffix)
