from django.conf import settings
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required

from . import services
from .crypto import generate_password
from .forms import AddExtensionForm, CreateDatabaseForm, DeleteConfirmForm, PasswordResetForm
from .models import UserDatabase
from .provisioner import ProvisionError

SESSION_PW_KEY = "gp_once_password_{}"


def _user_db(request, pk) -> UserDatabase:
    return get_object_or_404(
        UserDatabase.objects.select_related("server", "plan").exclude(status=UserDatabase.Status.DELETED),
        pk=pk, owner=request.user)


@site_user_required
def dashboard(request):
    dbs = (request.user.databases.exclude(status=UserDatabase.Status.DELETED)
           .select_related("server", "plan").prefetch_related("extensions"))
    can_create, reason = services.user_can_create(request.user)
    return render(request, "databases/dashboard.html", {"dbs": dbs, "can_create": can_create, "reason": reason})


@site_user_required
@require_http_methods(["GET", "POST"])
def create(request):
    plan = services.default_plan()
    can_create, reason = services.user_can_create(request.user)
    if not can_create:
        messages.warning(request, reason)
        return redirect("databases:dashboard")
    form = CreateDatabaseForm(request.POST or None, plan=plan,
                              initial={"password": generate_password()} if request.method == "GET" else None)
    if request.method == "POST" and form.is_valid():
        try:
            db = services.create_database(
                request.user, form.cleaned_data["label"], form.cleaned_data["password"],
                [e.name for e in form.cleaned_data["extensions"]], plan)
        except services.ServiceError as exc:
            messages.error(request, str(exc))
        else:
            request.session[SESSION_PW_KEY.format(db.pk)] = form.cleaned_data["password"]
            messages.success(request, "پایگاه داده مکانی شما آماده است 🎉")
            return redirect("databases:detail", pk=db.pk)
    if form.is_bound:
        selected = set(request.POST.getlist("extensions"))
    else:
        selected = {str(e.pk) for e in form.initial.get("extensions", [])}
    return render(request, "databases/create.html", {
        "form": form, "plan": plan, "selected": selected, "prefix": settings.TENANT_PREFIX})


@site_user_required
def detail(request, pk):
    db = _user_db(request, pk)
    once_password = request.session.pop(SESSION_PW_KEY.format(db.pk), None)
    return render(request, "databases/detail.html", {
        "db": db,
        "once_password": once_password,
        "pw_form": PasswordResetForm(initial={"password": generate_password()}),
        "ext_form": AddExtensionForm(db=db),
        "delete_form": DeleteConfirmForm(expected=db.label),
        "logs": db.logs.all()[:8],
    })


@site_user_required
@require_POST
def reset_password(request, pk):
    db = _user_db(request, pk)
    form = PasswordResetForm(request.POST)
    if not db.is_live:
        messages.error(request, "تغییر رمز فقط برای پایگاه داده فعال ممکن است.")
    elif form.is_valid():
        try:
            services.reset_password(db, form.cleaned_data["password"], request.user)
        except ProvisionError:
            messages.error(request, "تغییر رمز روی سرور ناموفق بود؛ لطفاً دوباره تلاش کنید.")
        else:
            request.session[SESSION_PW_KEY.format(db.pk)] = form.cleaned_data["password"]
            messages.success(request, "رمز پایگاه داده تغییر کرد. اتصال‌های QGIS و GeoServer را به‌روز کنید.")
    else:
        messages.error(request, " ".join(form.errors.get("password", [])))
    return redirect("databases:detail", pk=db.pk)


@site_user_required
@require_POST
def add_extension(request, pk):
    db = _user_db(request, pk)
    form = AddExtensionForm(request.POST, db=db)
    if db.is_live and form.is_valid():
        try:
            services.add_extension(db, form.cleaned_data["extension"], request.user)
            messages.success(request, f"افزونه «{form.cleaned_data['extension'].title}» نصب شد.")
        except (services.ServiceError, ProvisionError) as exc:
            messages.error(request, f"نصب افزونه ناموفق بود: {exc}")
    else:
        messages.error(request, "افزونه نامعتبر است.")
    return redirect("databases:detail", pk=db.pk)


@site_user_required
@require_POST
def renew(request, pk):
    db = _user_db(request, pk)
    try:
        services.renew(db, request.user)
        messages.success(request, "اعتبار پایگاه داده تمدید شد.")
    except (services.ServiceError, ProvisionError) as exc:
        messages.error(request, str(exc))
    return redirect("databases:detail", pk=db.pk)


@site_user_required
@require_POST
def delete(request, pk):
    db = _user_db(request, pk)
    form = DeleteConfirmForm(request.POST, expected=db.label)
    if not form.is_valid():
        messages.error(request, "نام وارد‌شده مطابقت نداشت؛ پایگاه داده حذف نشد.")
        return redirect("databases:detail", pk=db.pk)
    try:
        services.delete_database(db, request.user)
    except services.ServiceError as exc:
        messages.error(request, str(exc))
        return redirect("databases:detail", pk=db.pk)
    messages.success(request, "پایگاه داده و همه داده‌های آن حذف شد.")
    return redirect("databases:dashboard")
