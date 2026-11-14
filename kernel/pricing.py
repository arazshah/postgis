"""تعدیل قیمت فاکتور (نقطه‌ی توسعه): هر پلاگین می‌تواند برای کاربر تخفیف پیشنهاد دهد (مثلاً کد بازگشت).

- `register(name, quote, bind, plugin=...)`: `quote(user, amount) -> (مبلغ تازه، برچسب، توکن) | None`؛ `bind(token, invoice)` بعد از ساخت فاکتور.
- بهترین (کمترین) قیمت اعمال می‌شود؛ مبلغ هرگز کمتر از ۱ تومان یا بیشتر از قیمت پایه نمی‌شود. خطای یک تعدیل‌گر فاکتور را نمی‌شکند.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .jobs import load
from .plugins import registry

POINT = "pricing.adjuster"
log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Quote:
    amount: int
    base: int
    label: str = ""
    bind: str = ""
    token: Any = None

    @property
    def discount(self) -> int:
        return self.base - self.amount


def register(name: str, quote: str, bind: str, *, plugin: str, order: int = 100) -> None:
    registry.add(POINT, name, (quote, bind), plugin=plugin, order=order)


def quote(user, amount: int) -> Quote:
    best = Quote(amount, amount)
    for c in registry.contributions(POINT):
        quote_path, bind_path = c.value
        try:
            res = load(quote_path)(user, amount)
        except Exception:  # noqa: BLE001
            log.exception("pricing adjuster %s failed", c.key)
            continue
        if res and 1 <= res[0] < best.amount:
            best = Quote(int(res[0]), amount, res[1], bind_path, res[2])
    return best


def bind(q: Quote, invoice) -> None:
    if q.bind and q.discount > 0:
        try:
            load(q.bind)(q.token, invoice)
        except Exception:  # noqa: BLE001
            log.exception("pricing bind failed")
