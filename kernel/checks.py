"""بررسی‌های سیستم برای سکوی پلاگین (`manage.py check` و CI)."""
from django.core.checks import Error, register

from .plugins import registry


@register()
def plugins_ok(app_configs, **kwargs):
    out = [Error(f"پلاگین {app} بارگذاری نشد: {msg}", id="kernel.E001") for app, msg in registry.errors.items()]
    out += [Error(f"پلاگین {pid} به پلاگین نصب‌نشده‌ی {req} نیاز دارد.", id="kernel.E002")
            for pid, req in registry.missing_requirements()]
    from . import admin, jobs, nav, settings

    out += [Error(f"سهم {what} از پلاگین {plugin} تابع قابل‌بارگذاری ندارد: {err}", id="kernel.E003")
            for plugin, what, err in jobs.broken_handlers()]
    out += [Error(f"سهم {what} از پلاگین {plugin} تابع قابل‌بارگذاری ندارد: {err}", id="kernel.E004")
            for plugin, what, err in nav.broken_paths()]
    out += [Error(f"سهم {what} از پلاگین {plugin} نامعتبر است: {err}", id="kernel.E005")
            for plugin, what, err in settings.broken_paths()]
    out += [Error(f"سهم {what} از پلاگین {plugin} تابع قابل‌بارگذاری ندارد: {err}", id="kernel.E006")
            for plugin, what, err in admin.broken_paths()]
    return out
