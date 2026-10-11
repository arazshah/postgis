import csv

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required

from . import services
from .crypto import generate_password
from .explorer import EXPORT_LIMIT, MAP_LIMIT, SQL_MAX_ROWS, Explorer, ExplorerError
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
    from billing.services import unused_vouchers

    return render(request, "databases/dashboard.html", {"dbs": dbs, "can_create": can_create, "reason": reason,
                                                        "vouchers": unused_vouchers(request.user)})


@site_user_required
@require_http_methods(["GET", "POST"])
def create(request):
    from billing.models import PlanVoucher

    voucher = None
    voucher_id = request.GET.get("voucher") or request.POST.get("voucher")
    if voucher_id:
        voucher = PlanVoucher.objects.filter(pk=voucher_id if str(voucher_id).isdigit() else 0, user=request.user,
                                             used_by__isnull=True).select_related("plan").first()
        if voucher is None:
            messages.error(request, "این اعتبار پیدا نشد یا قبلاً استفاده شده است.")
            return redirect("databases:dashboard")
    plan = voucher.plan if voucher else services.default_plan()
    can_create, reason = services.user_can_create(request.user, ignore_limit=voucher is not None)
    if not can_create:
        messages.warning(request, reason)
        return redirect("databases:dashboard")
    form = CreateDatabaseForm(request.POST or None, plan=plan,
                              initial={"password": generate_password()} if request.method == "GET" else None)
    if request.method == "POST" and form.is_valid():
        try:
            db = services.create_database(
                request.user, form.cleaned_data["label"], form.cleaned_data["password"],
                [e.name for e in form.cleaned_data["extensions"]], plan,
                username=form.cleaned_data["username"], voucher=voucher)
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
        "form": form, "plan": plan, "selected": selected, "prefix": settings.TENANT_PREFIX, "voucher": voucher})


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


# ---------------------------------------------------------------------- مرورگر پایگاه داده
def _explorer_db(request, pk):
    db = _user_db(request, pk)
    if not db.is_live:
        messages.error(request, "مرورگر فقط برای پایگاه داده فعال در دسترس است.")
        return db, None
    return db, Explorer(db)


@site_user_required
def explore(request, pk):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:detail", pk=db.pk)
    return render(request, "databases/explore.html", {"db": db, "tables": tables, "section": "tables"})


@site_user_required
def explore_table(request, pk, schema, table):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    try:
        tables = ex.tables()
        t = next((x for x in tables if x.schema == schema and x.name == table), None)
        if t is None:
            raise ExplorerError("جدول پیدا نشد.")
        tab = request.GET.get("tab", "data")
        ctx = {"db": db, "tables": tables, "t": t, "tab": tab, "section": "tables"}
        if tab == "columns":
            ctx["columns"] = ex.columns(t)
        elif tab != "map":
            try:
                page = int(request.GET.get("page", "1"))
            except ValueError:
                page = 1
            ctx["data"] = ex.rows(t, page)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    return render(request, "databases/explore_table.html", ctx)


@site_user_required
def explore_geojson(request, pk, schema, table):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        raise Http404
    try:
        t = ex.find(schema, table)
        download = request.GET.get("download") == "1"
        data = ex.geojson(t, request.GET.get("column"), limit=EXPORT_LIMIT if download else MAP_LIMIT)
    except ExplorerError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    resp = HttpResponse(data, content_type="application/geo+json")
    if download:
        resp["Content-Disposition"] = f'attachment; filename="{schema}.{table}.geojson"'
    return resp


@site_user_required
def explore_csv(request, pk, schema, table):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        raise Http404
    try:
        t = ex.find(schema, table)
    except ExplorerError as exc:
        raise Http404 from exc

    class Echo:
        def write(self, value):
            return value

    writer = csv.writer(Echo())

    def stream():
        yield "﻿"  # BOM برای باز شدن درست فارسی در Excel
        for row in ex.export_rows(t):
            yield writer.writerow(row)

    resp = StreamingHttpResponse(stream(), content_type="text/csv; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{schema}.{table}.csv"'
    return resp


@site_user_required
@require_http_methods(["GET", "POST"])
def explore_sql(request, pk):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    query = request.POST.get("query", "") if request.method == "POST" else request.GET.get("q", "")
    allow_write = request.POST.get("allow_write") == "on"
    result = error = None
    if request.method == "POST":
        try:
            result = ex.run_sql(query, allow_write=allow_write)
        except ExplorerError as exc:
            error = str(exc)
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    return render(request, "databases/explore_sql.html", {
        "db": db, "tables": tables, "query": query, "allow_write": allow_write, "result": result,
        "error": error, "section": "sql", "max_rows": SQL_MAX_ROWS})
