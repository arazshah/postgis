from django.apps import AppConfig


class DeviceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "device"
    verbose_name = "دستگاه pgpro"

    def ready(self):
        from django.contrib import admin
        from django.http import HttpResponseRedirect
        from django.urls import reverse

        from . import signals  # noqa: F401

        # در دستگاه همه‌ی حساب‌ها «کاربر سایت» (is_staff=False) هستند و مدیر با is_superuser شناخته می‌شود؛
        # پنل مدیریت جنگو هم همین را می‌پذیرد و ورودش همان صفحه‌ی ورود دستگاه است.
        admin.site.has_permission = lambda request: bool(request.user.is_active and request.user.is_superuser)
        admin.site.login = lambda request, extra_context=None: HttpResponseRedirect(
            f"{reverse('accounts:login')}?next={request.GET.get('next', reverse('admin:index'))}")
