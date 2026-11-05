from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from accounts.models import User
from accounts.otp import client_ip
from databases.models import UserDatabase
from databases.services import logevent

from . import services, system, update
from .forms import LoginForm, PasswordChangeForm, UserForm
from .models import DeviceProfile

_DUMMY_HASH = None


def _dummy_check(raw: str):
    """هزینه‌ی زمانی بررسی رمز برای کاربر ناموجود هم یکسان باشد."""
    global _DUMMY_HASH
    if _DUMMY_HASH is None:
        _DUMMY_HASH = make_password("pgpro-dummy")
    check_password(raw, _DUMMY_HASH)


def _safe_next(request, value):
    if value and url_has_allowed_host_and_scheme(value, allowed_hosts={request.get_host()}, require_https=False):
        return value
    return None


def admin_required(view):
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_superuser:
            messages.error(request, "این بخش فقط برای مدیر دستگاه است.")
            return redirect("databases:dashboard")
        return view(request, *args, **kwargs)

    return wrapper


def home(request):
    return redirect("databases:dashboard" if request.user.is_authenticated else "accounts:login")


@require_http_methods(["GET", "POST"])
def login_view(request):
    """ورود با نام کاربری یا موبایل و رمز (جای ورود پیامکی نسخه‌ی ابری)."""
    if request.user.is_authenticated:
        return redirect("databases:dashboard")
    nxt = _safe_next(request, request.GET.get("next") or request.POST.get("next"))
    form = LoginForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        ident, raw = form.cleaned_data["identifier"], form.cleaned_data["password"]
        ip = client_ip(request)
        if services.is_locked(ip, ident):
            form.add_error(None, "به دلیل تلاش‌های ناموفق زیاد، ورود ۱۵ دقیقه قفل شد.")
        else:
            user = services.find_login(ident)
            ok = bool(user and user.is_active and user.check_password(raw))
            if user is None:
                _dummy_check(raw)
            if ok:
                services.clear_fails(ip, ident)
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect(nxt or "databases:dashboard")
            services.record_fail(ip, ident)
            form.add_error(None, "نام کاربری یا رمز عبور درست نیست.")
    return render(request, "device/login.html", {"form": form, "next": nxt or ""})


@login_required
@require_http_methods(["GET", "POST"])
def password_view(request):
    profile = DeviceProfile.objects.filter(user=request.user).first()
    forced = bool(profile and profile.must_change_password)
    form = PasswordChangeForm(request.POST or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        services.set_password(request.user, form.cleaned_data["new1"], must_change=False)
        update_session_auth_hash(request, request.user)
        logevent("password", "رمز عبور عوض شد.", user=request.user)
        messages.success(request, "رمز تازه ذخیره شد.")
        return redirect(_safe_next(request, request.POST.get("next") or request.GET.get("next")) or "databases:dashboard")
    return render(request, "device/password.html", {"form": form, "forced": forced,
                                                   "next": request.GET.get("next", "")})


# ---------------------------------------------------------------- کاربران
def _user_rows():
    users = User.objects.annotate(
        db_count=Count("databases", filter=~Q(databases__status=UserDatabase.Status.DELETED), distinct=True),
    ).select_related("device_profile").order_by("-is_superuser", "username", "phone")
    return list(users)


@admin_required
@require_http_methods(["GET", "POST"])
def users_view(request):
    create_form = UserForm(initial={"password": services.temp_password()})
    if request.method == "POST":
        action = request.POST.get("action", "")
        handler = {"create": _create, "edit": _edit, "reset": _reset, "toggle": _toggle, "delete": _delete}.get(action)
        if handler is None:
            return redirect("device:users")
        result = handler(request)
        if isinstance(result, UserForm):  # خطای فرم ساخت: همان مودال باز می‌ماند
            create_form = result
        else:
            return redirect("device:users")
    rows = _user_rows()
    secret = request.session.pop("dv_secret", None) if request.method == "GET" else None
    return render(request, "device/users.html", {"secret": secret,
        "rows": rows, "create_form": create_form, "open_create": request.method == "POST",
        "temp_password": services.temp_password(), "admins": sum(1 for u in rows if u.is_superuser and u.is_active),
    })


def _target(request) -> User | None:
    user = User.objects.filter(pk=request.POST.get("user") or 0).first()
    if user is None:
        messages.error(request, "کاربر پیدا نشد.")
    return user


def _create(request):
    form = UserForm(request.POST)
    if not form.is_valid():
        return form
    d = form.cleaned_data
    try:
        pw = d["password"] or services.temp_password()
        services.check_new_password(pw)
        user = services.create_user(d["username"], pw, full_name=d["full_name"], organization=d["organization"],
                                    phone=d["phone"], admin=d["role"] == "admin")
    except ValidationError as exc:
        form.add_error(None, exc)
        return form
    logevent("user", f"کاربر {user.username} ساخته شد.", user=request.user)
    request.session["dv_secret"] = {"who": user.username, "password": pw, "kind": "create"}
    messages.success(request, f"کاربر «{user.username}» ساخته شد.")


def _edit(request):
    user = _target(request)
    if user is None:
        return
    role_admin = request.POST.get("role") == "admin"
    if user.is_superuser and not role_admin and services.is_last_admin(user):
        messages.error(request, "دستگاه باید دست‌کم یک مدیر فعال داشته باشد.")
        return
    from accounts.models import normalize_mobile

    phone = (request.POST.get("phone") or "").strip()
    try:
        phone = normalize_mobile(phone) if phone else None
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return
    if phone and User.objects.filter(phone=phone).exclude(pk=user.pk).exists():
        messages.error(request, "این شماره‌ی موبایل برای حساب دیگری ثبت شده است.")
        return
    user.full_name = (request.POST.get("full_name") or "").strip()[:150]
    user.organization = (request.POST.get("organization") or "").strip()[:200]
    user.phone = phone
    user.is_superuser = role_admin
    user.save(update_fields=["full_name", "organization", "phone", "is_superuser"])
    logevent("user", f"کاربر {user.username or user.pk} ویرایش شد.", user=request.user)
    messages.success(request, "تغییرات ذخیره شد.")


def _reset(request):
    user = _target(request)
    if user is None:
        return
    pw = (request.POST.get("password") or "").strip() or services.temp_password()
    try:
        services.check_new_password(pw, user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return
    services.set_password(user, pw, must_change=True)
    logevent("user", f"رمز {user.username or user.pk} بازنشانی شد.", user=request.user)
    request.session["dv_secret"] = {"who": user.username or str(user.pk), "password": pw, "kind": "reset"}
    messages.success(request, "رمز بازنشانی شد؛ همه‌ی نشست‌های باز او بسته شد.")


def _toggle(request):
    user = _target(request)
    if user is None:
        return
    if user.pk == request.user.pk:
        messages.error(request, "حساب خودتان را نمی‌توانید غیرفعال کنید.")
        return
    if user.is_active and services.is_last_admin(user):
        messages.error(request, "دستگاه باید دست‌کم یک مدیر فعال داشته باشد.")
        return
    user.is_active = not user.is_active
    user.save(update_fields=["is_active"])
    logevent("user", f"کاربر {user.username or user.pk} {'فعال' if user.is_active else 'غیرفعال'} شد.", user=request.user)
    messages.success(request, "کاربر فعال شد." if user.is_active else "کاربر غیرفعال شد و دیگر نمی‌تواند وارد شود.")


def _delete(request):
    user = _target(request)
    if user is None:
        return
    if user.pk == request.user.pk:
        messages.error(request, "حساب خودتان را نمی‌توانید حذف کنید.")
        return
    if services.is_last_admin(user):
        messages.error(request, "آخرین مدیر دستگاه حذف نمی‌شود.")
        return
    if user.databases.exclude(status=UserDatabase.Status.DELETED).exists():
        messages.error(request, "این کاربر پایگاه داده دارد. اول پایگاه‌هایش را حذف کنید، یا فقط حسابش را غیرفعال کنید.")
        return
    name = user.username or user.pk
    user.delete()
    logevent("user", f"کاربر {name} حذف شد.", user=request.user)
    messages.success(request, "کاربر حذف شد.")


# ---------------------------------------------------------------- دستگاه
@admin_required
def system_view(request):
    from databases.models import DatabaseServer

    server = DatabaseServer.objects.filter(is_default=True).first()
    return render(request, "device/system.html", {"sys": system.snapshot(), "server": server,
                                                  "tz": settings.TIME_ZONE})


@admin_required
@require_POST
def update_start_view(request):
    ok, message = update.start(check_only=request.POST.get("mode") == "check")
    if ok:
        logevent("update", "به‌روزرسانی دستگاه شروع شد.", user=request.user)
    return JsonResponse({"ok": ok, "message": message}, status=200 if ok else 400)


@admin_required
def update_status_view(request):
    return JsonResponse(update.status())


@admin_required
@require_POST
def time_view(request):
    try:
        epoch = int(request.POST.get("epoch", ""))
    except ValueError:
        return JsonResponse({"ok": False, "message": "زمان مرورگر معتبر نیست."}, status=400)
    ok, message = system.set_system_time(epoch)
    if ok:
        logevent("time", f"ساعت دستگاه با مرورگر هماهنگ شد ({timezone.now():%Y-%m-%d %H:%M}).", user=request.user)
    return JsonResponse({"ok": ok, "message": message}, status=200 if ok else 400)
