"""«آزمایشگاه ژئوکدر» در پنل مدیریت (ADR-0009 مرحله‌ی ۵، آزمایش اولیه): مدیر فهرست نشانی را روی یک پایگاه می‌آزماید و نرخ تطبیق را می‌بیند.

چون بر داده‌ی یک پایگاه مشتری می‌خواند، فقط مدیر ارشد با تأیید تازه (stepup) و هر اجرا در لاگ ثبت می‌شود. نتیجه‌ی CSV ۱۵ دقیقه در حافظه‌ی
پنل می‌ماند. سقف: ۳۰۰ نشانی در هر اجرا.
"""
from __future__ import annotations

import csv
import io
import logging
import secrets

from django.contrib import admin, messages
from django.core.cache import cache
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import redirect
from django.template.response import TemplateResponse

from . import geocode, stepup, workspace

log = logging.getLogger(__name__)
MAX_LINES, TTL = 300, 900


def allowed(request) -> bool:
    u = request.user
    return bool(u.is_active and u.is_staff and u.is_superuser)


def _csv(results: list[geocode.Result]) -> str:
    out = io.StringIO()
    out.write("﻿")  # BOM: اکسل فارسی را درست باز کند
    w = csv.writer(out)
    w.writerow(["نشانی", "سطح", "اطمینان", "امتیاز", "طول", "عرض", "نام تطبیق‌خورده", "توضیح"])
    for r in results:
        w.writerow([_safe(r.text), geocode.LEVELS[r.level], r.label, r.score, r.lon if r.lon is not None else "", r.lat if r.lat is not None else "",
                    _safe(r.matched), _safe(r.note)])
    return out.getvalue()


def _safe(v: str) -> str:
    """جلوگیری از تزریق فرمول در اکسل (ورودی کاربر)."""
    v = str(v or "")
    return "'" + v if v[:1] in "=+-@\t\r" else v


def lab(request):
    if not allowed(request):
        raise PermissionDenied
    ctx = {**admin.site.each_context(request), "title": "آزمایشگاه ژئوکدر", "form": {"ws": "", "city": "", "radius": "15", "text": ""}}
    token = request.GET.get("dl")
    if token:
        data = cache.get(f"geolab:{request.user.pk}:{token}")
        if not data:
            messages.error(request, "نتیجه منقضی شده؛ دوباره اجرا کنید.")
            return redirect(request.path)
        resp = HttpResponse(data, content_type="text/csv; charset=utf-8")
        resp["Content-Disposition"] = 'attachment; filename="geocode-results.csv"'
        resp["Cache-Control"] = "no-store"
        return resp
    if request.method == "POST":
        if not stepup.ok(request):
            return redirect(stepup.url(request))
        post = request.POST
        ctx["form"] = {"ws": post.get("ws", ""), "city": post.get("city", ""), "radius": post.get("radius", "15"), "text": post.get("text", "")}
        lines = [ln.strip() for ln in post.get("text", "").splitlines() if ln.strip()]
        try:
            if not post.get("ws", "").isdigit():
                raise geocode.GeocodeError("شناسه‌ی پایگاه را (عدد) بدهید.")
            if not post.get("city", "").strip():
                raise geocode.GeocodeError("نام شهر را بدهید.")
            if not lines:
                raise geocode.GeocodeError("دست‌کم یک نشانی بدهید (هر سطر یک نشانی).")
            if len(lines) > MAX_LINES:
                raise geocode.GeocodeError(f"حداکثر {MAX_LINES} نشانی در هر اجرا.")
            try:
                radius = float(post.get("radius") or 15)
            except ValueError:
                raise geocode.GeocodeError("شعاع عدد (کیلومتر) باشد.") from None
            ws = workspace.peek(int(post["ws"]))
            if ws is None or not getattr(ws, "is_live", False):
                raise geocode.GeocodeError("پایگاه پیدا نشد یا فعال نیست.")
            gz = geocode.load(ws, post["city"], radius)
            results = geocode.geocode_many(gz, lines)
        except geocode.GeocodeError as exc:
            messages.error(request, str(exc))
        except Exception:  # noqa: BLE001 - خطای پایگاه داده‌ی مشتری: پیام ثابت
            log.exception("geocode lab failed")
            messages.error(request, "اجرا انجام نشد (دسترسی یا خواندن پایگاه داده).")
        else:
            log.warning("geocode lab: user %s ws %s city %s n=%s", request.user.pk, ws.pk, gz.city_name, len(lines))
            token = secrets.token_urlsafe(12)
            cache.set(f"geolab:{request.user.pk}:{token}", _csv(results), TTL)
            ctx.update(results=results, stats=geocode.stats(results), levels=geocode.LEVELS, city=gz.city_name, token=token,
                       n_streets=len(gz.streets), n_pois=len(gz.pois), n_hoods=len(gz.hoods))
    return TemplateResponse(request, "admin/kernel/geocode_lab.html", ctx)
