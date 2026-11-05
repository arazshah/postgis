from django.conf import settings
from django.urls import reverse


def vector_assets() -> dict | None:
    """نشانی‌های اسکریپت و سبک نقشه‌ی پایه‌ی آفلاین برای صفحه‌هایی که Leaflet را دیرهنگام بارگذاری می‌کنند
    (مثل مودال «انتخاب روی نقشه» در table-geom.js)؛ بدون فایل نقشه None."""
    from django.templatetags.static import static

    from iranmap import basemap

    if not basemap.available():
        return None
    return {
        "style": reverse("iranmap:style"),
        "css": static("vendor/maplibre/maplibre-gl.css"),
        "maplibre_js": static("vendor/maplibre/maplibre-gl.js"),
        "plugin_js": static("vendor/maplibre-leaflet/leaflet-maplibre-gl.js"),
        "helper_js": static("js/device-basemap.js"),
        "rtl_js": static("vendor/rtl-text/mapbox-gl-rtl-text.js"),
    }


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
