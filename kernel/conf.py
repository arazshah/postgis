"""تنظیمات هر پلاگین: پلاگین گزینه‌هایش را اعلام می‌کند، مدیر در پنل مقدار می‌دهد، کد با `conf.get` می‌خواند.

- مقدارها در جدول `PluginSetting` هستند (نه در تنظیمات سایت)؛ گزینه‌ی `secret` رمزنگاری‌شده (`kernel.crypto`) ذخیره می‌شود
  و هرگز در فرم یا لاگ برنگردانده می‌شود (فقط «تنظیم شده»).
- مقدار نامعتبر یا خراب هرگز استثنا نمی‌دهد: به پیش‌فرض اعلام‌شده برمی‌گردد.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from . import crypto
from .plugins import registry

OPTION = "conf.option"
KINDS = ("str", "int", "bool", "choice", "secret")


@dataclass(frozen=True)
class Option:
    plugin: str
    key: str
    label: str
    kind: str = "str"
    default: Any = None
    choices: tuple[tuple[str, str], ...] = ()
    help: str = ""
    min: int | None = None
    max: int | None = None


def option(plugin: str, key: str, label: str, *, kind: str = "str", default: Any = None, choices=(), help: str = "",
           min: int | None = None, max: int | None = None) -> None:
    if kind not in KINDS:
        raise ValueError(f"نوع گزینه نامعتبر است: {kind}")
    if kind == "choice" and not choices:
        raise ValueError("گزینه‌ی choice فهرست انتخاب می‌خواهد.")
    registry.add(OPTION, f"{plugin}.{key}", Option(plugin, key, label, kind, default, tuple(choices), help, min, max),
                 plugin=plugin)


def options(plugin: str) -> list[Option]:
    return [o for o in registry.values(OPTION) if o.plugin == plugin]


def _find(plugin: str, key: str) -> Option | None:
    return registry.get(OPTION, f"{plugin}.{key}")


def coerce(opt: Option, raw: Any) -> Any:
    """مقدار خام را به نوع گزینه درمی‌آورد؛ ValueError با پیام فارسی اگر نشد."""
    if opt.kind == "bool":
        return raw is True or str(raw).strip().lower() in ("1", "true", "on")
    if opt.kind == "int":
        try:
            v = int(raw)
        except (TypeError, ValueError):
            raise ValueError("عدد صحیح وارد کنید.") from None
        if opt.min is not None and v < opt.min or opt.max is not None and v > opt.max:
            raise ValueError(f"عدد باید بین {opt.min} و {opt.max} باشد.")
        return v
    v = str(raw if raw is not None else "").strip()
    if opt.kind == "choice" and v not in {c[0] for c in opt.choices}:
        raise ValueError("گزینه‌ی نامعتبر.")
    if len(v) > (4096 if opt.kind == "secret" else 2000):           # توکن‌های JWT بلندند
        raise ValueError("مقدار بیش از حد بلند است.")
    return v


def _value(opt: Option, row: str | None) -> Any:
    if row is None:
        return opt.default
    try:
        raw = crypto.decrypt(row) if opt.kind == "secret" else row
        return coerce(opt, raw) if opt.kind != "secret" else raw
    except ValueError:
        return opt.default


def get(plugin: str, key: str) -> Any:
    from .models import PluginSetting

    opt = _find(plugin, key)
    if opt is None:
        raise KeyError(f"گزینه‌ای به نام {plugin}.{key} اعلام نشده است.")
    return _value(opt, PluginSetting.objects.filter(plugin_id=plugin, key=key).values_list("value", flat=True).first())


def get_all(plugin: str) -> dict[str, Any]:
    """همه‌ی مقدارهای مؤثر یک پلاگین با یک پرس‌وجو (برای پلاگینی که ده‌ها گزینه دارد)."""
    from .models import PluginSetting

    rows = dict(PluginSetting.objects.filter(plugin_id=plugin).values_list("key", "value"))
    return {o.key: _value(o, rows.get(o.key)) for o in options(plugin)}


def is_set(plugin: str, key: str) -> bool:
    from .models import PluginSetting

    return PluginSetting.objects.filter(plugin_id=plugin, key=key).exists()


def set_value(plugin: str, key: str, raw: Any) -> None:
    """ذخیره‌ی مقدار (پس از اعتبارسنجی)؛ مقدار خالی برای secret یعنی «دست نزن»، برای بقیه یعنی بازگشت به پیش‌فرض."""
    from .models import PluginSetting

    opt = _find(plugin, key)
    if opt is None:
        raise KeyError(f"گزینه‌ای به نام {plugin}.{key} اعلام نشده است.")
    if opt.kind == "secret":
        if not str(raw or "").strip():
            return
        PluginSetting.objects.update_or_create(plugin_id=plugin, key=key, defaults={"value": crypto.encrypt(coerce(opt, raw))})
        return
    if raw in (None, "") and opt.kind != "bool":
        PluginSetting.objects.filter(plugin_id=plugin, key=key).delete()
        return
    PluginSetting.objects.update_or_create(plugin_id=plugin, key=key, defaults={"value": str(coerce(opt, raw))})


def clear(plugin: str, key: str) -> None:
    from .models import PluginSetting

    PluginSetting.objects.filter(plugin_id=plugin, key=key).delete()
