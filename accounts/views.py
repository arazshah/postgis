from django.contrib import messages
from django.contrib.auth import login
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from analytics import services as analytics
from analytics.models import Event
from core.models import SiteSettings

from . import otp
from .decorators import site_user_required
from .forms import PhoneForm, ProfileForm, VerifyForm
from .models import OTPCode, User

SESSION_PHONE = "otp_phone"
SESSION_NEXT = "otp_next"


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
    last = OTPCode.objects.filter(phone=phone).order_by("-created_at").first()
    return render(request, "accounts/verify.html", {
        "form": form, "phone": phone, "new_user": new_user,
        "wait": otp.seconds_until_resend(phone, conf),
        "via_bale": bool(last and last.channel == "bale"),
        "bale_button": conf.bale_ready and conf.bale_button,
        "bale_wait": otp.seconds_until_resend(phone, conf, "bale"),
    })


@require_POST
def resend(request):
    phone = request.session.get(SESSION_PHONE)
    if not phone:
        return redirect("accounts:login")
    channel = "bale" if request.POST.get("channel") == "bale" else "sms"
    result = otp.request_code(phone, otp.client_ip(request), channel=channel)
    (messages.success if result.ok else messages.error)(request, result.message)
    if result.debug_code:
        messages.info(request, f"حالت توسعه: کد {result.debug_code}")
    return redirect("accounts:verify")


@site_user_required
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST or None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "اطلاعات حساب ذخیره شد.")
        return redirect("accounts:profile")
    return render(request, "accounts/profile.html", {"form": form})
