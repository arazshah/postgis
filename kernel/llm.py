"""تنظیم مدل زبانی شخصی کاربر (آدرس، مدل و کلید رمزنگاری‌شده): سرویسی که پلاگین تحلیل پیاده می‌کند و بخش‌های دیگر
(مثل «پرسش فارسی» در کنسول SQL) فقط از اینجا می‌خوانند."""
from __future__ import annotations


class LlmConfigError(Exception):
    """خطای تنظیم مدل زبانی با پیام فارسی قابل نمایش."""


class Provider:
    def config(self, user):
        """تنظیم ذخیره‌شده‌ی کاربر (شیء با base_url، model، get_key()، key_hint) یا None."""
        raise NotImplementedError

    def save(self, user, base_url: str, model: str, key: str):
        """اعتبارسنجی و ذخیره؛ کلید خالی = کلید قبلی بماند. خطا = LlmConfigError."""
        raise NotImplementedError


_provider: Provider | None = None


def set_provider(provider: Provider) -> None:
    global _provider
    _provider = provider


def provider() -> Provider:
    if _provider is None:
        raise LlmConfigError("سرویس مدل زبانی در دسترس نیست.")
    return _provider


def config(user):
    return provider().config(user)


def save(user, base_url: str, model: str, key: str):
    return provider().save(user, base_url, model, key)
