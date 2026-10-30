"""ثبت بازدید و رویداد. هیچ خطایی از اینجا نباید به کاربر برسد."""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from . import classify as cl
from .models import Event, Visit, Visitor

log = logging.getLogger(__name__)

COOKIE = "gp_vid"
COOKIE_MAX_AGE = 365 * 24 * 3600
SESSION_GAP = timedelta(minutes=30)
SKIP_PREFIXES = ("/manage/", "/static/", "/media/", "/healthz", "/robots.txt", "/sitemap.xml", "/favicon",
                 "/api/", "/tiles/", "/ows/", "/go/")


def enabled() -> bool:
    return getattr(settings, "ANALYTICS_ENABLED", True)


def ip_hash(ip: str | None) -> str:
    """IP خام ذخیره نمی‌شود؛ هش با نمکِ روزانه فقط برای شمارش یکتا در همان روز کافی است."""
    if not ip:
        return ""
    day = timezone.now().strftime("%Y%m%d")
    return hashlib.sha256(f"{settings.SECRET_KEY}:{day}:{ip}".encode()).hexdigest()[:16]


def own_hosts() -> set[str]:
    hosts = {h.lower().removeprefix("www.") for h in settings.CANONICAL_REDIRECT_HOSTS}
    for url in (settings.CANONICAL_URL, settings.SITE_URL):
        host = url.split("://", 1)[-1].split("/", 1)[0].split(":", 1)[0].lower().removeprefix("www.")
        if host:
            hosts.add(host)
    return hosts


def _eligible(request, response) -> bool:
    if not enabled() or request.method != "GET" or response.status_code != 200:
        return False
    if request.path.startswith(SKIP_PREFIXES):
        return False
    if request.META.get("HTTP_DNT") == "1" or request.META.get("HTTP_SEC_GPC") == "1":
        return False
    if "text/html" not in response.get("Content-Type", ""):
        return False
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and user.is_staff:
        return False
    return not cl.is_bot(request.META.get("HTTP_USER_AGENT", ""))


def _client_ip(request):
    from accounts.otp import client_ip

    return client_ip(request)


def track_pageview(request, response) -> None:
    """از میدلور صدا زده می‌شود. شکست ثبت آمار هرگز صفحه را خراب نمی‌کند."""
    try:
        if not _eligible(request, response):
            return
        _track(request, response)
    except Exception:  # noqa: BLE001
        log.exception("analytics tracking failed")


ACTION_RETENTION_DAYS = 365
ACTION_STATUS_OK = (200, 201, 302, 303)


def track_action(request, response) -> None:
    """ریزکارهای کاربر واردشده (دیدن صفحه و ارسال فرم) برای خروجی اکسل. فقط نام مسیر و شناسه‌های آدرس؛ هرگز محتوای فرم."""
    try:
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated or user.is_staff or not enabled():
            return
        if request.path.startswith(SKIP_PREFIXES) or request.META.get("HTTP_DNT") == "1" \
                or request.META.get("HTTP_SEC_GPC") == "1" or request.headers.get("X-Requested-With"):
            return
        match = getattr(request, "resolver_match", None)
        if match is None or not match.view_name:
            return
        if request.method == "GET":
            if response.status_code != 200 or "text/html" not in response.get("Content-Type", ""):
                return
            prefix = Event.VIEW
        elif request.method == "POST":
            if response.status_code not in ACTION_STATUS_OK:
                return
            prefix = Event.DO
        else:
            return
        visitor, visit = _current(request)
        if visitor is None:
            return
        meta = {"route": match.view_name, "status": response.status_code,
                "ok": request.method == "GET" or response.status_code != 200}
        meta.update({k: v for k, v in match.kwargs.items() if isinstance(v, int | str) and len(str(v)) <= 64})
        Event.objects.create(visitor=visitor, visit=visit, name=(prefix + match.view_name)[:40],
                             path=request.path[:300], meta=meta)
    except Exception:  # noqa: BLE001
        log.exception("analytics action failed")


def _track(request, response) -> None:
    ua = request.META.get("HTTP_USER_AGENT", "")
    device, browser, in_app = cl.device_info(ua)
    now = timezone.now()
    vid = request.COOKIES.get(COOKIE, "")
    visitor = Visitor.objects.filter(vid=vid).first() if len(vid) == 32 else None
    is_new_visitor = visitor is None
    if is_new_visitor:
        vid = secrets.token_hex(16)
        visitor = Visitor(vid=vid)

    ref = cl.referrer_host(request.META.get("HTTP_REFERER", ""), own_hosts())
    info = cl.classify(request.GET, ref, in_app)
    fresh_click = bool(request.GET.get("utm_source") or info["click_id"] or ref)

    visit = None if is_new_visitor else visitor.visits.order_by("-last_seen").first()
    start_new = visit is None or now - visit.last_seen > SESSION_GAP
    if not start_new and fresh_click and \
            (info["source"], info["medium"], info["campaign"]) != (visit.source, visit.medium, visit.campaign):
        start_new = True  # کلیک تازه از تبلیغ یا سایت دیگر وسط نشست قبلی

    with transaction.atomic():
        if is_new_visitor:
            visitor.first_source, visitor.first_medium = info["source"], info["medium"]
            visitor.first_campaign = info["campaign"]
            visitor.first_referrer = ref
            visitor.first_landing = request.path[:300]
            visitor.device, visitor.browser, visitor.in_app = device, browser, in_app
            visitor.language = (request.META.get("HTTP_ACCEPT_LANGUAGE", "")[:2]).lower()
        visitor.last_seen = now
        if start_new:
            visitor.visits_count += 1
        visitor.save()
        if start_new:
            visit = Visit.objects.create(
                visitor=visitor, source=info["source"], medium=info["medium"], campaign=info["campaign"],
                content=info["content"], term=info["term"], click_id=info["click_id"], referrer_host=ref,
                referrer_url=request.META.get("HTTP_REFERER", "")[:300], landing_path=request.path[:300],
                last_path=request.path[:300], device=device, browser=browser, in_app=in_app,
                ip_hash=ip_hash(_client_ip(request)))
        else:
            Visit.objects.filter(pk=visit.pk).update(last_seen=now, last_path=request.path[:300],
                                                     pages=visit.pages + 1)
    request.analytics_visitor, request.analytics_visit = visitor, visit
    if is_new_visitor or request.COOKIES.get(COOKIE) != visitor.vid:
        response.set_cookie(COOKIE, visitor.vid, max_age=COOKIE_MAX_AGE, httponly=True, samesite="Lax",
                            secure=request.is_secure())


def _current(request):
    """بازدیدکننده و نشست فعلی؛ اگر میدلور برای این درخواست چیزی نساخته باشد از کوکی پیدا می‌شود."""
    visitor = getattr(request, "analytics_visitor", None)
    if visitor is not None:
        return visitor, getattr(request, "analytics_visit", None)
    vid = request.COOKIES.get(COOKIE, "")
    if len(vid) != 32:
        return None, None
    visitor = Visitor.objects.filter(vid=vid).first()
    visit = visitor.visits.order_by("-last_seen").first() if visitor else None
    return visitor, visit


def record(request, name: str, **meta) -> None:
    """رویداد قیف را به بازدیدکننده فعلی نسبت می‌دهد. بدون کوکی (یا DNT) چیزی ثبت نمی‌شود."""
    try:
        if not enabled() or request.META.get("HTTP_DNT") == "1" or request.META.get("HTTP_SEC_GPC") == "1":
            return
        visitor, visit = _current(request)
        if visitor is None:
            return
        Event.objects.create(visitor=visitor, visit=visit, name=name, path=request.path[:300], meta=meta)
    except Exception:  # noqa: BLE001
        log.exception("analytics event failed")


def attach_user(request, user, *, new_user: bool) -> None:
    """بعد از ورود موفق: بازدیدکننده به کاربر وصل می‌شود تا منبع اولین ورودش روی حساب بماند."""
    try:
        if not enabled():
            return
        visitor, visit = _current(request)
        if visitor is None:
            return
        if visitor.user_id is None:
            visitor.user = user
            visitor.linked_at = timezone.now()
            visitor.save(update_fields=["user", "linked_at"])
        Event.objects.create(visitor=visitor, visit=visit, name=Event.SIGNUP if new_user else Event.LOGIN,
                             path=request.path[:300], meta={})
    except Exception:  # noqa: BLE001
        log.exception("analytics attach failed")


def cleanup(days: int | None = None) -> dict:
    """داده خام قدیمی پاک می‌شود؛ بازدیدکننده‌های وصل‌شده به کاربر (منبع ثبت‌نام) می‌مانند."""
    days = days or getattr(settings, "ANALYTICS_RETENTION_DAYS", 90)
    cutoff = timezone.now() - timedelta(days=days)
    action_cutoff = timezone.now() - timedelta(days=max(days, ACTION_RETENTION_DAYS))
    acts = Event.objects.filter(created_at__lt=action_cutoff).filter(
        Q(name__startswith=Event.VIEW) | Q(name__startswith=Event.DO)).delete()[0]
    ev = acts + Event.objects.filter(created_at__lt=cutoff, visitor__user__isnull=True).delete()[0]
    vi = Visit.objects.filter(started_at__lt=cutoff, visitor__user__isnull=True).delete()[0]
    vr = Visitor.objects.filter(last_seen__lt=cutoff, user__isnull=True).delete()[0]
    return {"events": ev, "visits": vi, "visitors": vr}
