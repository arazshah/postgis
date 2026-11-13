"""تصویر آگهی بازارچه پلاگین (docs/adr/0010 مرحله‌ی ۸): آپلود امن در استودیو و نمایش عمومی با نشانی غیرقابل‌حدس.

- بایت‌های دریافتی هرگز مستقیم ذخیره یا نمایش داده نمی‌شوند: با Pillow باز، اندازه و نوع سنجیده، **بازرمزگذاری به WebP** (بی‌فراداده) و کوچک می‌شود.
- سقف: ۳ تصویر برای هر پلاگین، ۱ مگابایت ورودی، ۴۰۰۰×۴۰۰۰ پیکسل؛ فقط PNG، JPEG و WebP.
"""
from __future__ import annotations

import io
import secrets

from django.http import Http404, HttpResponse
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

from .models import PluginMedia

MAX_BYTES = 1_000_000
MAX_PIXELS = 4000 * 4000
MAX_SIDE = (1280, 800)
ALLOWED = {"PNG", "JPEG", "WEBP"}


class MediaError(ValueError):
    """پیام فارسی کوتاه."""


def store(plugin_id: str, raw: bytes) -> PluginMedia:
    from PIL import Image, UnidentifiedImageError

    if len(raw) > MAX_BYTES:
        raise MediaError("حجم تصویر بیش از ۱ مگابایت است.")
    if PluginMedia.objects.filter(plugin_id=plugin_id).count() >= PluginMedia.MAX_PER_PLUGIN:
        raise MediaError(f"حداکثر {PluginMedia.MAX_PER_PLUGIN} تصویر برای هر پلاگین؛ اول یکی را حذف کنید.")
    try:
        probe = Image.open(io.BytesIO(raw))
        if probe.format not in ALLOWED:
            raise MediaError("فقط PNG، JPEG یا WebP پذیرفته می‌شود.")
        if probe.width * probe.height > MAX_PIXELS or probe.width < 200 or probe.height < 120:
            raise MediaError("اندازه‌ی تصویر مجاز نیست (دست‌کم ۲۰۰×۱۲۰ و حداکثر ۴۰۰۰×۴۰۰۰ پیکسل).")
        img = Image.open(io.BytesIO(raw))
        img.load()
    except MediaError:
        raise
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError, ValueError):
        raise MediaError("تصویر خوانده نشد؛ فایل PNG، JPEG یا WebP سالم بدهید.") from None
    img = img.convert("RGBA" if img.mode in ("RGBA", "LA", "P") else "RGB")
    img.thumbnail(MAX_SIDE)
    out = io.BytesIO()
    img.save(out, "WEBP", quality=82)  # بازرمزگذاری: فراداده و بایت‌های اضافه‌ی فایل اصلی حذف می‌شود
    nxt = (PluginMedia.objects.filter(plugin_id=plugin_id).order_by("-order").values_list("order", flat=True).first() or 0) + 1
    return PluginMedia.objects.create(plugin_id=plugin_id, token=secrets.token_urlsafe(12)[:16], content_type="image/webp", data=out.getvalue(),
                                      width=img.width, height=img.height, order=nxt)


@require_GET
@cache_control(public=True, max_age=86400, immutable=True)
def serve(request, token):
    m = PluginMedia.objects.filter(token=token).first()
    if m is None:
        raise Http404
    r = HttpResponse(bytes(m.data), content_type=m.content_type)
    r["X-Content-Type-Options"] = "nosniff"
    r["Content-Security-Policy"] = "default-src 'none'; img-src 'self'; sandbox"
    return r
