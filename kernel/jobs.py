"""ثبت «نوع کار پس‌زمینه»: هر پلاگین handler، مقصد اعلان و متن‌های خودش را می‌آورد.

صف (مدل Job، claim، اجرا) در اپ jobs است و فقط از این رجیستری می‌خواند؛ پس jobs هیچ پلاگینی را نمی‌شناسد.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from importlib import import_module
from typing import Any

from .plugins import registry

log = logging.getLogger(__name__)
POINT = "job.kind"


@dataclass(frozen=True)
class JobKind:
    kind: str
    label: str
    handler: str  # مسیر نقطه‌ای «module.function»؛ دیر بار می‌شود تا راه‌اندازی سبک بماند
    plugin: str
    destination: str = ""  # نام url با یک آرگومان (شناسه‌ی پایگاه)؛ خالی = نمای کلی پایگاه
    fragment: str = ""  # مثلاً "#history"
    subject: str = ""  # تابع (job) -> str | None: نام کوتاه موضوع برای عنوان اعلان
    done_title: str = ""  # عنوان ثابت اعلان موفق؛ خالی = «<موضوع> تمام شد»
    notice: str = ""  # تابع (job, subject) -> dict | None: بازنویسی level/title/body/action اعلان موفق
    quiet_when_auto: bool = False  # کار خودکار موفق اعلان نسازد


def register_kind(kind: str, label: str, handler: str, *, plugin: str, **kw) -> JobKind:
    k = JobKind(kind=str(kind), label=label, handler=handler, plugin=plugin, **kw)
    registry.add(POINT, k.kind, k, plugin=plugin)
    return k


def get(kind: str) -> JobKind | None:
    return registry.get(POINT, str(kind))


def kinds() -> list[JobKind]:
    return registry.values(POINT)


def load(path: str) -> Callable[..., Any]:
    module, _, attr = path.rpartition(".")
    return getattr(import_module(module), attr)


def handler_for(kind: str) -> Callable[..., Any]:
    k = get(kind)
    if k is None:
        raise LookupError(f"نوع کار ناشناخته است: {kind}")
    return load(k.handler)


def call(path: str, *args):
    """فراخوانی قلاب اختیاری؛ مسیر خالی = None."""
    return load(path)(*args) if path else None


# ---------------------------------------------------------------------- کار دوره‌ای worker
TICK = "job.tick"


def register_tick(name: str, func: str, *, plugin: str, order: int = 100) -> None:
    """کار دوره‌ای (هر دقیقه در worker): مسیر تابع (now) -> نتیجه‌ی قابل‌چاپ."""
    registry.add(TICK, name, func, plugin=plugin, order=order)


def run_ticks(now=None) -> dict:
    """همه‌ی کارهای دوره‌ای ثبت‌شده؛ خطای یکی جلوی بقیه را نمی‌گیرد."""
    out = {}
    for c in registry.contributions(TICK):
        try:
            out[c.key] = load(c.value)(now)
        except Exception as exc:  # noqa: BLE001
            log.exception("tick %s (%s) failed", c.key, c.plugin)
            out[c.key] = f"خطا: {exc}"
    return out


def broken_handlers() -> list[tuple[str, str, str]]:
    """(پلاگین، نام سهم، خطا) برای هر مسیر تابعی که بار نمی‌شود؛ بررسی سیستم آن را گزارش می‌کند."""
    paths = [(k.plugin, f"job.kind:{k.kind}", p) for k in kinds() for p in (k.handler, k.subject, k.notice) if p]
    paths += [(c.plugin, f"{TICK}:{c.key}", c.value) for c in registry.contributions(TICK)]
    out = []
    for plugin, what, path in paths:
        try:
            load(path)
        except Exception as exc:  # noqa: BLE001
            out.append((plugin, what, f"{path}: {exc}"))
    return out
