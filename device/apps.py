from django.apps import AppConfig


class DeviceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "device"
    verbose_name = "دستگاه pgpro"

    def ready(self):
        from . import signals  # noqa: F401
