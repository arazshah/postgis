"""ثبت مسیر URL توسط پلاگین: پلاگین مسیر و نمای خودش را در یک «گروه» (فضای‌نام) ثبت می‌کند و URLconf همان گروه آن را سوار می‌کند.

چرا: بخش‌های یک پایگاه داده (جدول‌ها، SQL، یافتن، ورود…) هر کدام پلاگین جدا هستند ولی نشانی و نام مسیرشان (`databases:explore`…)
نباید عوض شود؛ پس صاحب فضای‌نام (`databases/urls.py`) فقط `routes.patterns("databases")` را می‌چیند و هیچ پلاگینی را import نمی‌کند.

- نما با مسیر نقطه‌ای ثبت می‌شود و هنگام ساخت URLconf (پس از کشف پلاگین‌ها) بار می‌شود.
- **پلاگین معیوب سایت را نمی‌خواباند:** اگر نما بار نشود، همان نام مسیر با نمایی که ۴۰۴ می‌دهد سوار می‌شود (تا `{% url %}` در
  صفحه‌های دیگر نشکند) و خطا در `registry.errors` و `manage.py check` دیده می‌شود.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from importlib import import_module

from django.http import Http404
from django.urls import path

from .plugins import registry

log = logging.getLogger(__name__)
POINT = "route"


@dataclass(frozen=True)
class Route:
    group: str
    route: str
    view: str  # مسیر نقطه‌ای «package.module.function»
    name: str
    plugin: str


EXT_GROUPS = ("ext", "ws_ext")  # گروه‌های مجاز پلاگین سطح ۳؛ مسیر باید با «<id>/» شروع شود


def add(group: str, route: str, view: str, name: str, *, plugin: str, order: int = 100) -> None:
    if group in EXT_GROUPS and not route.startswith(f"{plugin}/"):
        from .plugins import PluginError

        raise PluginError(f"مسیر {route!r} در گروه {group} باید با «{plugin}/» شروع شود.")
    registry.add(POINT, f"{group}:{name}", Route(group, route, view, name, plugin), plugin=plugin, order=order)


def routes(group: str) -> list[Route]:
    return [r for r in registry.values(POINT) if r.group == group]


def _load(dotted: str):
    module, _, attr = dotted.rpartition(".")
    return getattr(import_module(module), attr)


def _unavailable(plugin: str):
    def view(request, *args, **kwargs):
        raise Http404(f"بخش «{plugin}» در دسترس نیست.")

    view.__module__ = __name__  # صاحبش هسته است؛ دروازه‌ی مجوز کاری با آن ندارد
    return view


def patterns(group: str) -> list:
    """الگوهای URL یک گروه به ترتیب order؛ برای `urlpatterns += routes.patterns("…")` در URLconf صاحب فضای‌نام."""
    registry.discover()
    out = []
    for r in routes(group):
        try:
            view = _load(r.view)
        except Exception as exc:  # noqa: BLE001  نمای معیوب: نام مسیر می‌ماند، صفحه ۴۰۴ می‌دهد
            log.exception("route %s:%s (%s) failed to load", r.group, r.name, r.plugin)
            registry.errors.setdefault(r.plugin, f"مسیر {r.name}: {type(exc).__name__}: {exc}")
            view = _unavailable(r.plugin)
        out.append(path(r.route, view, name=r.name))
    return out


def on(name: str, *, user=None, ws=None) -> bool:
    """مسیر «گروه:نام» برای این کاربر و فضای کار روشن و مجاز است؟ مسیر ثبت‌نشده (میزبان یا اپ دیگر) همیشه روشن است.

    پیوندی که به بخش خاموش یا محدودشده می‌رود نباید ساخته شود (وگرنه کاربر به ۴۰۴ می‌رسد)."""
    from . import entitlements

    r = registry.get(POINT, name)
    return True if r is None else entitlements.allowed(r.plugin, user=user, ws=ws)


def broken() -> list[tuple[str, str, str]]:
    """(پلاگین، نام مسیر، خطا) برای بررسی سیستم."""
    out = []
    for r in registry.values(POINT):
        try:
            _load(r.view)
        except Exception as exc:  # noqa: BLE001
            out.append((r.plugin, f"{r.group}:{r.name}", f"{type(exc).__name__}: {exc}"))
    return out
