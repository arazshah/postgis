from django.conf import settings
from django.urls import reverse


def device(request):
    from iranmap import basemap

    return {
        # نشانی style.json نقشه‌ی پایه‌ی آفلاین ایران؛ فقط وقتی فایل iran.pmtiles روی دستگاه هست
        "DEVICE_BASEMAP_URL": reverse("iranmap:style") if basemap.available() else "",
        "DEVICE_MODE": True,
        "DEVICE_NAME": settings.DEVICE_NAME,
        "DEVICE_VERSION": settings.DEVICE_VERSION,
        "ROBOTS": "noindex, nofollow",
    }
