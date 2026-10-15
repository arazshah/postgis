"""نقشه پایه برداری ایران: کاشی‌ها و سبک MapLibre."""
from __future__ import annotations

from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.http import require_http_methods

from publish import access
from publish.models import ApiKey

from . import basemap

CACHE = 7 * 24 * 3600


def _cors(resp):
    resp["Access-Control-Allow-Origin"] = "*"
    resp["Access-Control-Allow-Headers"] = "Authorization, X-API-Key"
    return resp


def _err(status, msg):
    return _cors(JsonResponse({"code": status, "description": msg}, status=status,
                              json_dumps_params={"ensure_ascii": False}))


def same_site(request) -> bool:
    """درخواست از صفحه‌های خود سایت (نقشه‌های عمومی، embed، طراح نقشه)؟"""
    if request.headers.get("Sec-Fetch-Site") in ("same-origin", "same-site"):
        return True
    ref = request.headers.get("Referer") or request.headers.get("Origin") or ""
    return bool(ref) and urlsplit(ref).netloc == request.get_host()


def _external(request):
    """استفاده در سایت دیگر: کلید API یک پایگاه داده با پلن دارای نقشه پایه؛ از سهمیه روزانه کم می‌شود."""
    raw = access.raw_key(request)
    if not raw:
        raise access.Denied(401, "Unauthorized", "برای استفاده از نقشه پایه در سایت خودتان کلید API بفرستید (?key=).")
    key = (ApiKey.objects.select_related("database__plan")
           .filter(key_hash=ApiKey.digest(raw), revoked_at__isnull=True).first()) if raw.startswith(ApiKey.PREFIX) else None
    if key is None:
        raise access.Denied(403, "Forbidden", "کلید API نامعتبر یا باطل شده است.")
    db = key.database
    access.check_database(db)
    if not db.plan.basemap_api:
        raise access.Denied(403, "Forbidden", "نقشه پایه ایران برای سایت‌های بیرونی در پلن‌های پولی فعال است.")
    access.count(db)


@require_http_methods(["GET", "HEAD", "OPTIONS"])
def tile(request, z, x, y):
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    if not basemap.available():
        return _err(404, "نقشه پایه هنوز روی این سرور ساخته نشده است.")
    if z > 22 or x >= 2 ** z or y >= 2 ** z:
        return _err(400, "مختصات کاشی نامعتبر است.")
    if not same_site(request):
        try:
            _external(request)
        except access.Denied as exc:
            return _err(exc.status, exc.message)
    data, gz = basemap.tile(z, x, y)
    if not data:
        resp = HttpResponse(status=204)
    else:
        resp = HttpResponse(data, content_type="application/vnd.mapbox-vector-tile")
        if gz:
            resp["Content-Encoding"] = "gzip"
    resp["Cache-Control"] = f"public, max-age={CACHE}"
    resp["Vary"] = "Origin"
    return _cors(resp)


@require_http_methods(["GET", "OPTIONS"])
def style(request):
    if request.method == "OPTIONS":
        return _cors(HttpResponse(status=204))
    if not basemap.available():
        return _err(404, "نقشه پایه هنوز روی این سرور ساخته نشده است.")
    base = request.build_absolute_uri("/").rstrip("/")
    doc = basemap.style(base, request.build_absolute_uri(settings.STATIC_URL))
    key = request.GET.get("key")
    if key:
        doc["sources"]["protomaps"]["tiles"] = [t + "?" + urlencode({"key": key}) for t in
                                                doc["sources"]["protomaps"]["tiles"]]
    resp = JsonResponse(doc, json_dumps_params={"ensure_ascii": False})
    resp["Cache-Control"] = "public, max-age=3600"
    return _cors(resp)
