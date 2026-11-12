"""بازار پلاگین (docs/adr/0008): هسته نمی‌داند «فروش» چگونه است؛ صورتحساب یک ارائه‌دهنده ثبت می‌کند.

ویزارد و بازار مشتری فقط با این قرارداد کار می‌کنند:
- `upsert(plugin_id, listing)` یک آگهی (قیمت، مدت، واحد خرید، دوره‌ی آزمایشی، سقف‌ها) را می‌سازد یا به‌روز می‌کند؛
- `remove(plugin_id)` آگهی را از فروشگاه برمی‌دارد (پلاگین و مجوزهای موجود می‌مانند).
هسته هیچ اپی را import نمی‌کند: ارائه‌دهنده مسیر تابع است که `billing/plugin.py` ثبت می‌کند.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .jobs import load
from .plugins import registry

POINT = "market.provider"
SCOPES = ("workspace", "user")


class MarketError(Exception):
    """پیام فارسی کوتاه."""


@dataclass(frozen=True)
class Listing:
    title: str
    summary: str = ""
    price_toman: int = 0
    duration_days: int = 30
    scope: str = "workspace"
    trial_days: int = 0
    limits: dict = field(default_factory=dict)
    is_public: bool = True

    def validate(self) -> None:
        if not self.title.strip():
            raise MarketError("عنوان آگهی لازم است.")
        if self.scope not in SCOPES:
            raise MarketError("واحد خرید باید پایگاه داده یا حساب کاربر باشد.")
        if not 0 <= int(self.price_toman) <= 1_000_000_000:
            raise MarketError("قیمت نامعتبر است.")
        if not 1 <= int(self.duration_days) <= 3650:
            raise MarketError("مدت باید بین ۱ و ۳۶۵۰ روز باشد.")
        if not 0 <= int(self.trial_days) <= 90:
            raise MarketError("دوره‌ی آزمایشی بین ۰ و ۹۰ روز باشد.")
        if not isinstance(self.limits, dict) or any(not isinstance(v, (int, float)) or isinstance(v, bool) for v in self.limits.values()):
            raise MarketError("سقف‌ها باید عددی باشند.")


def provider(func: str, *, plugin: str) -> None:
    """ارائه‌دهنده‌ی فروش: مسیر تابع `(action, plugin_id, listing|None) -> None`."""
    registry.add(POINT, "provider", func, plugin=plugin, replace=True)


def _call(action: str, plugin_id: str, listing: Listing | None) -> None:
    func = registry.get(POINT, "provider")
    if func is None:
        raise MarketError("فروش پلاگین فعال نیست (ارائه‌دهنده‌ی صورتحساب ثبت نشده).")
    load(func)(action, plugin_id, listing)


def available() -> bool:
    return registry.get(POINT, "provider") is not None


def upsert(plugin_id: str, listing: Listing) -> None:
    if plugin_id not in registry.plugins:
        raise MarketError("این پلاگین نصب نیست.")
    listing.validate()
    _call("upsert", plugin_id, listing)


def remove(plugin_id: str) -> None:
    if available():
        _call("remove", plugin_id, None)
