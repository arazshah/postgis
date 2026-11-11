from django.apps import AppConfig


class KernelConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "kernel"
    verbose_name = "هسته"

    def ready(self):
        from . import checks  # noqa: F401  ثبت بررسی‌های سیستم
        from .plugins import registry

        registry.discover()
