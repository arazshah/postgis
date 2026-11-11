from django.apps import AppConfig


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kernel"
    verbose_name = "هسته"

    def ready(self):
        from . import checks, entitlements  # noqa: F401  ثبت بررسی‌های سیستم و شنونده‌ی پاک‌سازی مجوز
        from .signals import connect

        connect()
        from .plugins import registry

        registry.discover()
        from . import jobs

        jobs.register_tick("plugin_alerts", "kernel.alerts.tick", plugin="kernel", order=90)
        jobs.register_tick("plugin_breaker", "kernel.health.tick", plugin="kernel", order=95)
