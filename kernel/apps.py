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
        jobs.register_tick("notify_poll", "kernel.notify.tick", plugin="kernel", order=92)
        jobs.register_tick("plugin_breaker", "kernel.health.tick", plugin="kernel", order=95)
        from . import dash

        dash.attention("kernel.admin_cards.attention", plugin="kernel", order=5)
        dash.attention("kernel.admin_cards.ext_state", plugin="kernel", order=6)
