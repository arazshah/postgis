import re

from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.forms import PasswordChangeForm, SetPasswordForm
from django.core.cache import cache
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from analytics import services as analytics
from analytics.models import Event
from core.models import SiteSettings

from . import otp
from .decorators import site_user_required
from .forms import EmailSignupForm, PasswordLoginForm, PhoneForm, ProfileForm, VerifyForm
from .models import User, normalize_mobile

SESSION_PHONE = "otp_phone"
SESSION_NEXT = "otp_next"

LOGIN_MAX_FAILS = 8
LOGIN_WINDOW = 15 * 60
SIGNUP_MAX_PER_IP = 10
SIGNUP_WINDOW = 60 * 60


def _bump(key: str, window: int) -> None:
    try:
        cache.incr(key)
    except ValueError:
        cache.set(key, 1, window)


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()},
                                                 require_https=request.is_secure()):
        return value
    return None


@require_http_methods(["GET", "POST"])
def login_start(request):
    """قدم اول ورود یا ثبت‌نام: گرفتن شماره موبایل و ارسال کد."""
    if request.user.is_authenticated:
        return redirect("databases:dashboard")
    nxt = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    cta = request.GET.get("cta", "")
    if request.method == "GET" and re.fullmatch(r"[a-z0-9-]{1,30}", cta):
        analytics.record(request, Event.CTA_CLICK, where=cta)  # دکمه‌ی «شروع رایگان» صفحه‌های عمومی
    form = PhoneForm(request.POST or None, initial={"phone": request.session.get(SESSION_PHONE, "")})
    if request.method == "POST" and form.is_valid():
        phone = form.cleaned_data["phone"]
        existing = User.objects.filter(phone=phone).first()
        if existing is None and not SiteSettings.get().signup_open:
            messages.error(request, "ثبت‌نام کاربر جدید فعلاً بسته است.")
            return render(request, "accounts/login.html", {"form": form, "next": nxt or ""})
        if existing is not None and existing.is_staff:
            messages.error(request, "این شماره به حساب مدیریتی متصل است و از اینجا وارد نمی‌شود.")
            return render(request, "accounts/login.html", {"form": form, "next": nxt or ""})
        result = otp.request_code(phone, otp.client_ip(request))
        if result.ok:
            analytics.record(request, Event.OTP_REQUESTED, new=existing is None)
        elif not result.wait_seconds:
            analytics.record(request, Event.OTP_SEND_FAILED, new=existing is None)
        if result.ok or result.wait_seconds:
            request.session[SESSION_PHONE] = phone
            if nxt:
                request.session[SESSION_NEXT] = nxt
            if result.ok:
                messages.success(request, result.message)
                if result.debug_code:
                    messages.info(request, f"حالت توسعه: کد {result.debug_code}")
            return redirect("accounts:verify")
        messages.error(request, result.message)
    return render(request, "accounts/login.html", {"form": form, "next": nxt or ""})


@require_http_methods(["GET", "POST"])
def login_password(request):
    """ورود با ایمیل (یا موبایل) و رمز عبور؛ برای کسانی که پیامک برایشان نمی‌رسد."""
    if request.user.is_authenticated:
        return redirect("databases:dashboard")
    nxt = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = PasswordLoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ident = form.cleaned_data["identifier"]
        ip = otp.client_ip(request) or "na"
        key_ip, key_id = f"pwfail:ip:{ip}", f"pwfail:id:{ident.lower()}"
        if cache.get(key_ip, 0) >= LOGIN_MAX_FAILS * 3 or cache.get(key_id, 0) >= LOGIN_MAX_FAILS:
            form.add_error(None, "به دلیل تلاش‌های ناموفق زیاد، ورود ۱۵ دقیقه قفل شد.")
        else:
            lookup = {"email__iexact": ident} if "@" in ident else None
            if lookup is None:
                try:
                    lookup = {"phone": normalize_mobile(ident)}
                except Exception:  # noqa: BLE001
                    lookup = {}
            user = User.objects.filter(is_staff=False, **lookup).first() if lookup else None
            if user is not None and user.has_usable_password() and user.check_password(form.cleaned_data["password"]):
                if not user.is_active:
                    form.add_error(None, "این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.")
                else:
                    cache.delete(key_id)
                    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                    analytics.attach_user(request, user, new_user=False)
                    return redirect(nxt or "databases:dashboard")
            else:
                if user is None:
                    User().set_password(form.cleaned_data["password"])  # زمان پاسخ برای حساب ناموجود هم یکسان بماند
                _bump(key_ip, LOGIN_WINDOW)
                _bump(key_id, LOGIN_WINDOW)
                form.add_error(None, "ایمیل/موبایل یا رمز عبور اشتباه است.")
    return render(request, "accounts/login_password.html", {"form": form, "next": nxt or ""})


@require_http_methods(["GET", "POST"])
def signup_email(request):
    """ثبت‌نام با ایمیل و رمز عبور؛ فعلاً ایمیل تأیید نمی‌شود."""
    if request.user.is_authenticated:
        return redirect("databases:dashboard")
    nxt = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = EmailSignupForm(request.POST or None)
    ctx = {"form": form, "next": nxt or ""}
    if request.method == "POST" and form.is_valid():
        if not SiteSettings.get().signup_open:
            messages.error(request, "ثبت‌نام کاربر جدید فعلاً بسته است.")
            return render(request, "accounts/signup_email.html", ctx)
        key = f"signup:ip:{otp.client_ip(request) or 'na'}"
        if cache.get(key, 0) >= SIGNUP_MAX_PER_IP:
            messages.error(request, "تعداد ثبت‌نام از این اینترنت زیاد بود. کمی بعد دوباره تلاش کنید.")
            return render(request, "accounts/signup_email.html", ctx)
        _bump(key, SIGNUP_WINDOW)
        d = form.cleaned_data
        user = User.objects.create_user(
            None, password=d["password"], email=d["email"], full_name=d["full_name"],
            organization=d.get("organization", ""))
        login(request, user, backend="django.contrib.auth.backends.ModelBackend")
        analytics.attach_user(request, user, new_user=True)
        messages.success(request, "حساب شما ساخته شد. حالا اولین پایگاه داده مکانی خود را بسازید.")
        return redirect("databases:create")
    return render(request, "accounts/signup_email.html", ctx)


@require_http_methods(["GET", "POST"])
def verify(request):
    """قدم دوم: بررسی کد؛ برای کاربر جدید نام و پذیرش قوانین هم گرفته می‌شود."""
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("accounts:login")
    user = User.objects.filter(phone=phone).first()
    if user is not None and user.is_staff:
        request.session.pop(SESSION_PHONE, None)
        return redirect("accounts:login")
    new_user = user is None
    form = VerifyForm(request.POST or None, new_user=new_user)

    if request.method == "POST" and form.is_valid():
        ok, error = otp.verify_code(phone, form.cleaned_data["code"])
        if not ok:
            analytics.record(request, Event.OTP_WRONG, new=new_user)
            form.add_error("code", error)
        else:
            if new_user and not SiteSettings.get().signup_open:
                messages.error(request, "ثبت‌نام کاربر جدید فعلاً بسته است.")
                return redirect("accounts:login")
            if new_user:
                user = User.objects.create_user(
                    phone, full_name=form.cleaned_data["full_name"],
                    organization=form.cleaned_data.get("organization", ""),
                    phone_verified_at=timezone.now())
            elif not user.is_active:
                messages.error(request, "این حساب غیرفعال شده است. با پشتیبانی تماس بگیرید.")
                return redirect("accounts:login")
            else:
                user.phone_verified_at = user.phone_verified_at or timezone.now()
                user.save(update_fields=["phone_verified_at"])
            request.session.pop(SESSION_PHONE, None)
            nxt = request.session.pop(SESSION_NEXT, None)
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            analytics.record(request, Event.OTP_VERIFIED, new=new_user)
            analytics.attach_user(request, user, new_user=new_user)
            if new_user:
                messages.success(request, "حساب شما ساخته شد. حالا اولین پایگاه داده مکانی خود را بسازید.")
                return redirect("databases:create")
            return redirect(nxt or "databases:dashboard")

    conf = SiteSettings.get()
    return render(request, "accounts/verify.html", {
        "form": form, "phone": phone, "new_user": new_user,
        "wait": otp.seconds_until_resend(phone, conf),
    })


@require_POST
def resend(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("accounts:login")
    result = otp.request_code(phone, otp.client_ip(request))
    (messages.success if result.ok else messages.error)(request, result.message)
    if result.debug_code:
        messages.info(request, f"حالت توسعه: کد {result.debug_code}")
    return redirect("accounts:verify")


@site_user_required
@require_http_methods(["GET", "POST"])
def profile(request):
    """پروفایل: مشخصات، تنظیم مدل زبانی (برای پرسش فارسی در همه‌ی پایگاه‌ها) و اطلاعات حساب."""
    from analysis.models import LlmConfig
    from databases import nl2sql

    cfg = LlmConfig.objects.filter(user=request.user).first()
    nxt = _safe_next(request, request.POST.get("next") or request.GET.get("next"))
    action = request.POST.get("action", "profile") if request.method == "POST" else ""
    form = ProfileForm(request.POST if action == "profile" else None, instance=request.user)
    pw_cls = PasswordChangeForm if request.user.has_usable_password() else SetPasswordForm
    pw_form = pw_cls(request.user, request.POST if action == "password" else None)
    if request.method == "POST":
        if action == "profile" and form.is_valid():
            form.save()
            messages.success(request, "اطلاعات حساب ذخیره شد.")
            return redirect("accounts:profile")
        if action == "password":
            if pw_form.is_valid():
                pw_form.save()
                update_session_auth_hash(request, request.user)
                messages.success(request, "رمز عبور ذخیره شد.")
                return redirect(f"{reverse('accounts:profile')}#account")
            messages.error(request, "رمز عبور ذخیره نشد؛ خطاها را در بخش «حساب و امنیت» ببینید.")
        if action == "llm_save":
            try:
                nl2sql.save_config(request.user, request.POST.get("base_url", ""), request.POST.get("model", ""),
                                   request.POST.get("api_key", ""))
            except nl2sql.NLError as exc:
                messages.error(request, str(exc))
                return redirect(f"{reverse('accounts:profile')}#ai")
            messages.success(request, "تنظیم مدل زبانی ذخیره شد.")
            return redirect(nxt or f"{reverse('accounts:profile')}#ai")
        if action == "llm_delete":
            if cfg:
                cfg.delete()
                messages.success(request, "کلید مدل زبانی حذف شد.")
            return redirect(f"{reverse('accounts:profile')}#ai")
    return render(request, "accounts/profile.html", {"form": form, "pw_form": pw_form, "cfg": cfg,
                                                    "next": nxt or "", "open_tab": "account" if action == "password" else ""})
