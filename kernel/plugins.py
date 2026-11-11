"""هسته‌ی پلاگین: مانیفست هر پلاگین و رجیستری «نقاط توسعه».

قاعده‌ی وابستگی (docs/adr/0004): هسته هیچ اپی را import نمی‌کند؛ هر اپ در `plugin.py` خودش را معرفی و
سهم‌هایش را ثبت می‌کند. `registry.discover()` در `KernelConfig.ready` ماژول `plugin` همه‌ی اپ‌های نصب‌شده را بار می‌کند.
پلاگینی که بارگذاری‌اش خطا بدهد سایت را نمی‌خواباند: خطا در `registry.errors` می‌ماند و `manage.py check` آن را گزارش می‌کند.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from importlib import import_module
from importlib.util import find_spec
from typing import Any

log = logging.getLogger(__name__)

API_VERSION = 1
ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
KINDS = ("system", "feature", "custom")


class PluginError(Exception):
    pass


@dataclass(frozen=True)
class Plugin:
    """مانیفست یک پلاگین. kind: system (همراه ایمیج، خاموش‌نشدنی) | feature | custom (اختصاصی مشتری)."""
    id: str
    name: str
    kind: str = "feature"
    version: str = "1.0.0"
    api: int = API_VERSION
    requires: tuple[str, ...] = ()
    description: str = ""


@dataclass(frozen=True)
class Contribution:
    point: str
    key: str
    value: Any
    plugin: str
    order: int = 100


@dataclass
class Registry:
    plugins: dict[str, Plugin] = field(default_factory=dict)
    errors: dict[str, str] = field(default_factory=dict)
    _points: dict[str, dict[str, Contribution]] = field(default_factory=dict)
    _discovered: bool = False

    # ------------------------------------------------------------------ پلاگین
    def register(self, id: str, name: str, **kw) -> Plugin:
        p = Plugin(id=id, name=name, **{**kw, "requires": tuple(kw.get("requires", ()))})
        if not ID_RE.fullmatch(p.id):
            raise PluginError(f"شناسه‌ی پلاگین نامعتبر است: {p.id!r}")
        if p.kind not in KINDS:
            raise PluginError(f"نوع پلاگین {p.id} نامعتبر است: {p.kind!r}")
        if p.api > API_VERSION:
            raise PluginError(f"پلاگین {p.id} نسخه‌ی قرارداد {p.api} می‌خواهد؛ هسته {API_VERSION} است.")
        old = self.plugins.get(p.id)
        if old is not None and old != p:
            raise PluginError(f"پلاگین {p.id} دو بار با مشخصات متفاوت ثبت شده است.")
        self.plugins[p.id] = p
        return p

    # ------------------------------------------------------------------ نقاط توسعه
    def add(self, point: str, key: str, value: Any, *, plugin: str, order: int = 100, replace: bool = False) -> None:
        bucket = self._points.setdefault(point, {})
        old = bucket.get(key)
        if old is not None and not replace and (old.plugin != plugin or old.value != value):
            raise PluginError(f"{point}:{key} پیش‌تر توسط پلاگین {old.plugin} ثبت شده است.")
        bucket[key] = Contribution(point, key, value, plugin, order)

    def get(self, point: str, key: str, default: Any = None) -> Any:
        c = self._points.get(point, {}).get(key)
        return default if c is None else c.value

    def contributions(self, point: str) -> list[Contribution]:
        """سهم‌های یک نقطه، مرتب بر اساس order و سپس ترتیب ثبت (پایدار)."""
        return sorted(self._points.get(point, {}).values(), key=lambda c: c.order)

    def values(self, point: str) -> list[Any]:
        return [c.value for c in self.contributions(point)]

    def points(self) -> list[str]:
        return sorted(self._points)

    def remove_plugin(self, plugin_id: str) -> None:
        """پلاگین و همه‌ی سهم‌هایش را برمی‌دارد (بارگذاری‌شده‌ی پویا؛ پلاگین داخلی هرگز)."""
        self.plugins.pop(plugin_id, None)
        self.errors.pop(plugin_id, None)
        for bucket in self._points.values():
            for key in [k for k, c in bucket.items() if c.plugin == plugin_id]:
                del bucket[key]

    # ------------------------------------------------------------------ کشف
    def discover(self, force: bool = False) -> None:
        if self._discovered and not force:
            return
        from django.apps import apps

        for cfg in apps.get_app_configs():
            name = f"{cfg.name}.plugin"
            try:
                if find_spec(name) is None:
                    continue
            except (ImportError, ValueError):
                continue
            try:
                import_module(name)
            except Exception as exc:  # noqa: BLE001  پلاگین معیوب نباید سایت را بخواباند
                log.exception("plugin %s failed to load", cfg.name)
                self.errors[cfg.name] = f"{type(exc).__name__}: {exc}"
        self._discovered = True

    def missing_requirements(self) -> list[tuple[str, str]]:
        return [(p.id, r) for p in self.plugins.values() for r in p.requires if r not in self.plugins]


registry = Registry()
register = registry.register
