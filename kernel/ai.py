"""قرارداد هوش مصنوعی هسته (docs/adr/0010): هسته مدل زبانی را نمی‌شناسد؛ پلاگین `assistant` آن را پیاده می‌کند.

- `chat` فقط متن می‌گیرد و متن برمی‌گرداند؛ ابزار، شبکه‌ی دلخواه و دسترسی به داده‌ی مشتری ندارد.
- سهمیه، ثبت مصرف و کلید API کار پیاده‌ساز است (تنظیم «دستیار سایت» در پنل)؛ خطا همیشه `AiError` با پیام فارسی امن است.
"""
from __future__ import annotations


class AiError(Exception):
    """پیام فارسی قابل نمایش (بدون کلید یا بدنه‌ی خطای ارائه‌دهنده)."""


class Provider:
    def available(self) -> bool:
        raise NotImplementedError

    def chat(self, user, purpose: str, messages: list[dict], max_tokens: int | None = None) -> str:
        """پاسخ مدل برای `messages` (role/content). `purpose` برچسب کوتاه کاربرد (مثل «studio»)؛ AiError اگر نشد."""
        raise NotImplementedError


_provider: Provider | None = None


def set_provider(provider: Provider | None) -> None:
    global _provider
    _provider = provider


def available() -> bool:
    try:
        return _provider is not None and _provider.available()
    except Exception:  # noqa: BLE001 - خرابی پیاده‌ساز نباید صفحه را بخواباند
        return False


def chat(user, purpose: str, messages: list[dict], max_tokens: int | None = None) -> str:
    if _provider is None:
        raise AiError("سرویس هوش مصنوعی در دسترس نیست.")
    return _provider.chat(user, purpose, messages, max_tokens)
