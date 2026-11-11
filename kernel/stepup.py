"""تأیید مجدد برای کارهای حساس پنل (مثلاً فعال‌سازی پلاگین): هسته نمی‌داند ورود دومرحله‌ای چگونه کار می‌کند.

پلاگین حساب `ok` و `url` را ثبت می‌کند. بدون ثبت (یا وقتی ورود دومرحله‌ای خاموش است) همه‌چیز مجاز است.
"""
from __future__ import annotations


class Provider:
    def ok(self, request) -> bool:
        """درخواست‌دهنده به‌تازگی رمز دوم را داده است؟"""
        raise NotImplementedError

    def url(self, request) -> str:
        """نشانی صفحه‌ی تأیید، با بازگشت به همین صفحه."""
        raise NotImplementedError


_provider: Provider | None = None


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def ok(request) -> bool:
    return True if _provider is None else _provider.ok(request)


def url(request) -> str:
    return "" if _provider is None else _provider.url(request)
