"""ورود دومرحله‌ی پنل مدیریت: پس از رمز عبور، رمز زمانی برنامه‌ی تأییدکننده (TOTP) یا یک کد بازیابی.

- هر مسیر `/manage/…` برای مدیر واردشده تا تأیید عامل دوم بسته است (به‌جز ورود، خروج و خود صفحه‌ی تأیید).
- مدیری که هنوز ثبت‌نام نکرده، همان لحظه به ثبت‌نام هدایت می‌شود (ثبت‌نام اجباری)؛ رمز عبور تنها دیگر کافی نیست.
- رمز هر گام یک‌بار پذیرفته می‌شود؛ پنج شکست پشت‌سرهم ۱۵ دقیقه قفل می‌کند؛ نشست پس از تأیید چرخانده می‌شود.
- کارهای حساس (فعال‌سازی پلاگین) تأیید «تازه» می‌خواهند (پیش‌فرض ۳۰ دقیقه): kernel.stepup.
- راه اضطراری قفل‌شدن: `manage.py admin_2fa_reset <نام‌کاربری>` یا کنش «بازنشانی» برای مدیر کامل در فهرست مدیران.
"""
from __future__ import annotations

import time
from urllib.parse import quote

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_http_methods

from kernel import stepup

from . import totp
from .models import AdminTOTP

SESSION_KEY = "admin_2fa"
MAX_FAILS, LOCK_SECONDS = 5, 15 * 60
EXEMPT = ("admin:login", "admin:logout", "admin_2fa", "admin:jsi18n")


def required() -> bool:
    return bool(getattr(settings, "ADMIN_2FA_REQUIRED", False))


def is_admin(request) -> bool:
    u = getattr(request, "user", None)
    return bool(u and u.is_authenticated and u.is_staff)


def _state(request) -> dict:
    s = request.session.get(SESSION_KEY) or {}
    return s if isinstance(s, dict) else {}


def verified(request, within_minutes: int | None = None) -> bool:
    """عامل دوم برای همین مدیر و همین نشست تأیید شده (و نه قدیمی‌تر از سقف)؟"""
    if not required():
        return True
    s = _state(request)
    if s.get("uid") != request.user.pk:
        return False
    age = time.time() - float(s.get("at", 0))
    limit = (within_minutes * 60) if within_minutes else getattr(settings, "ADMIN_2FA_MAX_AGE_HOURS", 12) * 3600
    return 0 <= age <= limit


def mark_verified(request) -> None:
    request.session.cycle_key()  # تثبیت نشست
    request.session[SESSION_KEY] = {"uid": request.user.pk, "at": time.time()}


class Provider(stepup.Provider):
    def ok(self, request) -> bool:
        return verified(request, getattr(settings, "ADMIN_2FA_FRESH_MINUTES", 30))

    def url(self, request) -> str:
        return f"{reverse('admin_2fa')}?fresh=1&next={quote(request.get_full_path())}"


# ---------------------------------------------------------------------- میان‌افزار
class Admin2FAMiddleware:
    """بسته بودن `/manage/…` برای مدیر واردشده‌ای که عامل دومش را نداده (در process_view چون نام نما آن‌جا معلوم است)."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_view(self, request, view_func, view_args, view_kwargs):
        if not required() or not request.path.startswith(reverse("admin:index")):
            return None
        if not is_admin(request) or verified(request):
            return None
        match = request.resolver_match
        if match is not None and match.view_name in EXEMPT:
            return None
        nxt = request.get_full_path() if request.method in ("GET", "HEAD") else ""
        return redirect(reverse("admin_2fa") + (f"?next={quote(nxt)}" if nxt else ""))


# ---------------------------------------------------------------------- صفحه‌ی تأیید و ثبت‌نام
def _fail_key(user) -> str:
    return f"a2fa:{user.pk}"


def _locked(user) -> bool:
    return cache.get(_fail_key(user), 0) >= MAX_FAILS


def _fail(user) -> None:
    try:
        cache.incr(_fail_key(user))
    except ValueError:
        cache.set(_fail_key(user), 1, LOCK_SECONDS)


def _safe_next(request) -> str:
    nxt = request.POST.get("next") or request.GET.get("next") or ""
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok and nxt.startswith(reverse("admin:index")) else reverse("admin:index")


def _check(rec: AdminTOTP, raw: str) -> bool:
    """رمز زمانی یا کد بازیابی (یک‌بارمصرف)؛ موفق = رکورد به‌روز می‌شود."""
    code = (raw or "").strip()
    step = totp.verify(rec.secret, code, rec.last_step)
    if step is not None:
        rec.last_step = step
        rec.save(update_fields=["last_step"])
        return True
    h = totp.recovery_hash(code)
    if h in (rec.recovery_hashes or []):
        rec.recovery_hashes = [x for x in rec.recovery_hashes if x != h]
        rec.save(update_fields=["recovery_hashes"])
        return True
    return False


def _context(request, **extra) -> dict:
    from django.contrib import admin

    return {**admin.site.each_context(request), "has_permission": False, "title": "ورود دومرحله‌ای",
            "next": _safe_next(request), **extra}


@never_cache
@require_http_methods(["GET", "POST"])
def twofa(request):
    if not is_admin(request):
        return redirect(f"{reverse('admin:login')}?next={reverse('admin_2fa')}")
    user = request.user
    rec = AdminTOTP.objects.filter(user=user).first()
    enrolled = bool(rec and rec.confirmed_at)
    action = request.POST.get("action", "")
    if request.method == "POST" and _locked(user):
        messages.error(request, "به دلیل تلاش‌های ناموفق زیاد، تأیید ۱۵ دقیقه قفل شد.")
        return render(request, "admin/2fa.html", _context(request, mode="verify" if enrolled else "enroll", locked=True))
    # --- ثبت‌نام (اجباری تا تمام شود)
    if not enrolled:
        rec = rec or AdminTOTP.start(user)
        if request.method == "POST":
            step = totp.verify(rec.secret, request.POST.get("code", ""), rec.last_step)
            if step is None:
                _fail(user)
                messages.error(request, "رمز درست نبود؛ رمز فعلی برنامه را دوباره بنویسید.")
            else:
                codes = totp.new_recovery_codes()
                rec.last_step, rec.confirmed_at = step, timezone.now()
                rec.recovery_hashes = [totp.recovery_hash(c) for c in codes]
                rec.save()
                cache.delete(_fail_key(user))
                mark_verified(request)
                return render(request, "admin/2fa.html", _context(request, mode="codes", codes=codes))
        return render(request, "admin/2fa.html", _context(
            request, mode="enroll", secret=totp.pretty(rec.secret), uri=totp.otpauth_uri(user.get_username(), rec.secret)))
    # --- تأیید
    if request.method == "POST" and action == "regenerate" and verified(request):
        if _check(rec, request.POST.get("code", "")):
            codes = totp.new_recovery_codes()
            rec.recovery_hashes = [totp.recovery_hash(c) for c in codes]
            rec.save(update_fields=["recovery_hashes"])
            cache.delete(_fail_key(user))
            mark_verified(request)
            return render(request, "admin/2fa.html", _context(request, mode="codes", codes=codes))
        _fail(user)
        messages.error(request, "رمز درست نبود.")
    elif request.method == "POST":
        if _check(rec, request.POST.get("code", "")):
            cache.delete(_fail_key(user))
            mark_verified(request)
            return redirect(_safe_next(request))
        _fail(user)
        messages.error(request, "رمز یا کد بازیابی درست نبود.")
    mode = "manage" if verified(request) and request.GET.get("manage") else "verify"
    if mode == "verify" and verified(request) and request.method == "GET" and not request.GET.get("fresh"):
        return redirect(_safe_next(request))
    return render(request, "admin/2fa.html", _context(request, mode=mode, remaining=len(rec.recovery_hashes or [])))
