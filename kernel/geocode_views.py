"""ابزار مشتری «ژئوکدر فارسی» (پلاگین `cap_geocoder`، ADR-0009 مرحله‌ی ۵): فهرست نشانی ← مختصات و اطمینان روی داده‌ی OSM همان پایگاه.

فقط‌خواندنی (هیچ چیزی در پایگاه نوشته نمی‌شود)؛ خروجی CSV برای دانلود. هر اجرا ≤ ۳۰۰ نشانی؛ مصرف با `geocode_rows` شمرده و با سقف مجوز سنجیده می‌شود.
"""
from __future__ import annotations

import logging
import secrets

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render

from . import caps, geocode, metering, workspace

log = logging.getLogger(__name__)
MAX_LINES, MAX_UPLOAD, TTL, PER_MIN = 300, 1_000_000, 900, 6
RADII = (5, 10, 15, 25, 40)


def _rate(user) -> bool:
    ck = f"geocode-rate:{user.pk}"
    cache.add(ck, 0, 60)
    try:
        return cache.incr(ck) <= PER_MIN
    except ValueError:
        return True


@login_required
def tool(request, pk):
    ws = workspace.get(request, pk, "viewer")
    if not caps.allowed("geocoder", user=request.user, ws=ws):
        raise Http404
    token = request.GET.get("dl")
    if token:
        data = cache.get(f"geotool:{request.user.pk}:{pk}:{token}")
        if not data:
            messages.error(request, "نتیجه منقضی شده؛ دوباره اجرا کنید.")
            return redirect(request.path)
        resp = HttpResponse(data, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="geocode-results.csv"'
        resp["Cache-Control"] = "no-store"
        resp["X-Content-Type-Options"] = "nosniff"
        return resp
    ctx = {"db": ws, "section": "geocode", "radii": RADII, "form": {"city": "", "radius": "15", "text": "", "column": ""}, "max_lines": MAX_LINES,
           "cities": [], "setup_error": ""}
    if not ws.is_live:
        ctx["setup_error"] = "ابزار فقط برای پایگاه داده‌ی فعال در دسترس است."
        return render(request, "kernel/geocode_tool.html", ctx)
    try:
        ctx["cities"] = [c.name for c in geocode.cities(ws)][:300]
    except geocode.GeocodeError as exc:
        ctx["setup_error"] = str(exc)
    except Exception:  # noqa: BLE001
        log.exception("geocode cities failed")
        ctx["setup_error"] = "خواندن فهرست شهرها ممکن نشد."
    if request.method == "POST" and not ctx["setup_error"]:
        post = request.POST
        ctx["form"] = {"city": post.get("city", ""), "radius": post.get("radius", "15"), "text": post.get("text", ""), "column": post.get("column", "")}
        try:
            lines = [ln.strip() for ln in post.get("text", "").splitlines() if ln.strip()]
            up = request.FILES.get("file")
            if up is not None:
                if up.size > MAX_UPLOAD:
                    raise geocode.GeocodeError("فایل حداکثر ۱ مگابایت باشد.")
                lines += geocode.lines_from_upload(up.read(MAX_UPLOAD + 1), post.get("column", ""))
            if not post.get("city", "").strip():
                raise geocode.GeocodeError("نام شهر را بنویسید یا از فهرست انتخاب کنید.")
            if not lines:
                raise geocode.GeocodeError("دست‌کم یک نشانی بدهید (هر سطر یک نشانی) یا فایل CSV بارگذاری کنید.")
            if len(lines) > MAX_LINES:
                raise geocode.GeocodeError(f"حداکثر {MAX_LINES} نشانی در هر اجرا.")
            try:
                radius = float(post.get("radius") or 15)
            except ValueError:
                raise geocode.GeocodeError("شعاع عدد باشد.") from None
            if not _rate(request.user):
                raise geocode.GeocodeError("درخواست زیاد بود؛ یک دقیقه بعد دوباره تلاش کنید.")
            within, _used, cap = metering.check("cap_geocoder", "geocode_rows", user=request.user, ws=ws)
            if not within:
                raise geocode.GeocodeError(f"سقف ماهانه‌ی نشانی ({cap}) پر شده است.")
            gz = geocode.load(ws, post["city"], radius)
            results = geocode.geocode_many(gz, lines)
        except geocode.GeocodeError as exc:
            messages.error(request, str(exc))
        except Exception:  # noqa: BLE001
            log.exception("geocode tool failed")
            messages.error(request, "اجرا انجام نشد (خواندن پایگاه داده).")
        else:
            metering.record("cap_geocoder", "geocode_rows", len(lines), user=request.user, ws=ws)
            workspace.log_event("plugin_geocode", f"ژئوکدر: {len(lines)} نشانی در {gz.city_name}", user=request.user, database=ws)
            tok = secrets.token_urlsafe(12)
            cache.set(f"geotool:{request.user.pk}:{pk}:{tok}", geocode.results_csv(results), TTL)
            ctx.update(results=results, stats=geocode.stats(results), city=gz.city_name, token=tok)
    return render(request, "kernel/geocode_tool.html", ctx)
