"""مسیرهای دستگاه pgpro: همان مسیرهای ژئوپایگاه + صفحه‌های دستگاه؛ صفحه‌ی اول به ورود/داشبورد می‌رود."""
from django.urls import include, path

from config.urls import urlpatterns as base_patterns
from device import views as device_views

urlpatterns = [
    path("", device_views.home, name="device_home"),
    path("device/", include("device.urls")),
    *base_patterns,
]
