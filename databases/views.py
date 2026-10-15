import csv

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required

from . import services
from .crypto import generate_password
from .explorer import EXPORT_LIMIT, MAP_LIMIT, SQL_MAX_ROWS, Explorer, ExplorerError
from .forms import AddExtensionForm, CreateDatabaseForm, DeleteConfirmForm, PasswordResetForm
from .models import UserDatabase
from .provisioner import ProvisionError

SESSION_PW_KEY = "gp_once_password_{}"


def _user_db(request, pk, need: str = "owner") -> UserDatabase:
    """پایگاه داده با بررسی سطح دسترسی (مالک، ویرایشگر یا مشاهده‌گر عضو تیم)؛ در غیر این صورت ۴۰۴."""
    from . import team

    return team.get_db(request, pk, need)


@site_user_required
def dashboard(request):
    from . import team

    team.link_pending(request.user)
    dbs = (request.user.databases.exclude(status=UserDatabase.Status.DELETED)
           .select_related("server", "plan").prefetch_related("extensions"))
    shared = team.shared_with(request.user)
    can_create, reason = services.user_can_create(request.user)
    from billing.services import unused_vouchers

    return render(request, "databases/dashboard.html", {"dbs": dbs, "shared": shared, "can_create": can_create,
                                                        "reason": reason,
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
    server = services.pick_server()
    return render(request, "databases/create.html", {
        "form": form, "plan": plan, "selected": selected, "prefix": settings.TENANT_PREFIX, "voucher": voucher,
        "public_port": server.public_port if server else None})


@site_user_required
def detail(request, pk):
    db = _user_db(request, pk, "viewer")
    if not db.is_mine:
        return render(request, "databases/shared.html", {"db": db})
    once_password = request.session.pop(SESSION_PW_KEY.format(db.pk), None)
    return render(request, "databases/detail.html", {
        "db": db,
        "once_password": once_password,
        "pw_form": PasswordResetForm(initial={"password": generate_password()}),
        "ext_form": AddExtensionForm(db=db),
        "delete_form": DeleteConfirmForm(expected=db.label),
        "logs": db.logs.all()[:8],
        "last_backup": db.jobs.filter(kind="backup", status="done").first(),
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


# ---------------------------------------------------------------------- بکاپ و بازگردانی
@site_user_required
def backups(request, pk):
    from jobs.models import Job

    db = _user_db(request, pk)
    jobs = list(db.jobs.filter(kind__in=[Job.Kind.BACKUP, Job.Kind.RESTORE]).select_related("source")[:40])
    return render(request, "databases/backups.html", {
        "db": db, "jobs": jobs, "busy": any(j.active for j in jobs),
        "available": [j for j in jobs if j.downloadable],
        "restore_form": DeleteConfirmForm(expected=db.label),
        "keep_days": db.plan.backup_retention_days,
    })


@site_user_required
@require_POST
def backup_new(request, pk):
    from jobs import services as jobs

    db = _user_db(request, pk)
    try:
        jobs.request_backup(db, request.user)
    except jobs.JobError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "بکاپ در صف قرار گرفت. معمولاً چند دقیقه طول می‌کشد؛ این صفحه را تازه کنید.")
    return redirect("databases:backups", pk=db.pk)


@site_user_required
def backup_download(request, pk, job_id):
    from django.http import FileResponse, Http404

    db = _user_db(request, pk)
    job = get_object_or_404(db.jobs, pk=job_id)
    if not job.downloadable or not job.path.exists():
        raise Http404
    return FileResponse(job.path.open("rb"), as_attachment=True, filename=job.path.name,
                        content_type="application/octet-stream")


@site_user_required
@require_POST
def backup_restore(request, pk, job_id):
    from jobs import services as jobs

    db = _user_db(request, pk)
    backup = get_object_or_404(db.jobs, pk=job_id)
    form = DeleteConfirmForm(request.POST, expected=db.label)
    if not form.is_valid():
        messages.error(request, "نام وارد‌شده مطابقت نداشت؛ بازگردانی انجام نشد.")
        return redirect("databases:backups", pk=db.pk)
    try:
        jobs.request_restore(db, backup, request.user)
    except jobs.JobError as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "بازگردانی در صف قرار گرفت. قبل از آن یک بکاپ ایمنی از وضع فعلی گرفته می‌شود.")
    return redirect("databases:backups", pk=db.pk)


# ---------------------------------------------------------------------- مرورگر پایگاه داده
def _explorer_db(request, pk, need: str = "viewer"):
    db = _user_db(request, pk, need)
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
    allow_write = request.POST.get("allow_write") == "on" and db.can_edit
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


# ---------------------------------------------------------------------- خروجی چندقالبی
@site_user_required
def explore_export(request, pk, schema, table, fmt):
    from django.http import FileResponse

    from . import gdal

    db, ex = _explorer_db(request, pk)
    if ex is None or fmt not in gdal.EXPORT_FORMATS:
        raise Http404
    try:
        t = ex.find(schema, table)
    except ExplorerError as exc:
        raise Http404 from exc
    workdir = gdal.new_workdir()
    try:
        geom = t.geometry[0]["column"] if t.geometry else None
        path = gdal.export_table(db, t.schema, t.name, fmt, workdir, geom_col=geom)
        fh = path.open("rb")  # فایل باز می‌ماند؛ پوشه موقت همین حالا پاک می‌شود
    except gdal.GdalError as exc:
        messages.error(request, f"ساخت خروجی ممکن نشد: {exc}")
        return redirect("databases:explore_table", pk=db.pk, schema=schema, table=table)
    finally:
        import shutil

        shutil.rmtree(workdir, ignore_errors=True)
    return FileResponse(fh, as_attachment=True, filename=path.name)


# ---------------------------------------------------------------------- پزشک داده
@site_user_required
@require_http_methods(["GET", "POST"])
def explore_health(request, pk):
    from .gdal import SRID_CHOICES

    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    if request.method == "POST":
        if not db.can_edit:
            messages.error(request, "برای اصلاح داده باید ویرایشگر یا مالک باشید.")
        elif db.status != UserDatabase.Status.ACTIVE:
            messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است؛ اصلاح ممکن نیست.")
        else:
            try:
                if request.POST.get("fix") == "all":
                    done, failed = ex.fix_all()
                    if done:
                        messages.success(request, f"{len(done)} مورد اصلاح شد.".translate(_FA))
                    for f in failed:
                        messages.error(request, f)
                    return redirect("databases:explore_health", pk=db.pk)
                srid = int(request.POST.get("srid") or 0) or None
                msg = ex.fix(request.POST.get("fix", ""), request.POST.get("schema", ""),
                             request.POST.get("table", ""), request.POST.get("column") or None, srid)
                messages.success(request, f"{request.POST.get('table')}: {msg}")
            except (ExplorerError, ValueError) as exc:
                messages.error(request, str(exc))
        return redirect("databases:explore_health", pk=db.pk)
    try:
        tables = ex.tables()
        issues = ex.health()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables, issues = [], []
    return render(request, "databases/explore_health.html", {
        "db": db, "tables": tables, "issues": issues, "section": "health", "fixes": Explorer.FIXES,
        "srid_choices": SRID_CHOICES})


# ---------------------------------------------------------------------- ورود فایل
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _import_job(db, job_id):
    from jobs.models import Job

    return get_object_or_404(db.jobs, pk=job_id, kind=Job.Kind.IMPORT)


@site_user_required
@require_http_methods(["GET", "POST"])
def import_start(request, pk):
    import shutil
    from pathlib import Path

    from django.conf import settings

    from jobs.models import Job
    from jobs.services import import_dir

    from . import gdal

    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    max_mb = settings.IMPORT_MAX_MB
    error = None
    if request.method == "POST":
        f = request.FILES.get("file")
        ext = Path(f.name).suffix.lower() if f else ""
        free = max(0, db.quota_bytes - db.size_bytes)
        if db.status != UserDatabase.Status.ACTIVE:
            error = "پایگاه داده فقط‌خواندنی یا غیرفعال است؛ ورود داده ممکن نیست."
        elif not f:
            error = "فایلی انتخاب نشده است."
        elif ext not in gdal.ALLOWED_EXT:
            error = "این قالب پشتیبانی نمی‌شود. Shapefile را zip کنید؛ یا GeoPackage، GeoJSON، KML، CSV و DXF بفرستید."
        elif f.size > max_mb * 1024 * 1024:
            error = f"حجم فایل بیشتر از {max_mb} مگابایت است."
        elif f.size * 1.3 > free:
            error = "فضای خالی پایگاه داده برای این فایل کافی نیست. پلن را ارتقا دهید یا داده‌های اضافه را حذف کنید."
        else:
            job = Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, database=db, user=request.user,
                                     params={"file": f"upload{ext}", "original": f.name[:200]})
            folder = import_dir(job)
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / f"upload{ext}", "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
            try:
                info = gdal.inspect(folder / f"upload{ext}")
            except gdal.GdalError as exc:
                shutil.rmtree(folder, ignore_errors=True)
                job.delete()
                error = f"فایل خوانده نشد: {exc}"
            else:
                existing = {t.name for t in ex.tables() if t.schema == "public"}
                for lyr in info["layers"]:
                    lyr["selected"] = bool(lyr["geom_type"] or ext == ".csv")
                    lyr["exists"] = lyr["table"] in existing
                    lyr["mode"] = "create"
                    lyr["to4326"] = False
                job.params = {**job.params, **info}
                job.save(update_fields=["params"])
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    recent = db.jobs.filter(kind="import").exclude(status="draft")[:5]
    return render(request, "databases/import.html", {
        "db": db, "tables": ex.tables(), "section": "import", "error": error, "max_mb": max_mb,
        "accept": ",".join(sorted(gdal.ALLOWED_EXT)), "recent": recent})


@site_user_required
@require_http_methods(["GET", "POST"])
def import_review(request, pk, job_id):
    from jobs.models import Job
    from jobs.services import import_dir

    from . import gdal

    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    job = _import_job(db, job_id)
    layers = job.params.get("layers", [])
    errors = []
    if request.method == "POST" and job.status == Job.Status.DRAFT:
        if request.POST.get("action") == "cancel":
            import shutil

            shutil.rmtree(import_dir(job), ignore_errors=True)
            job.delete()
            return redirect("databases:import", pk=db.pk)
        enc = request.POST.get("encoding") or None
        if job.params.get("encoding") and enc in ("UTF-8", "CP1256") and enc != job.params["encoding"]:
            job.params["encoding"] = enc
            path = import_dir(job) / job.params["file"]
            for lyr in layers:
                lyr["sample"] = gdal.sample(path, lyr["name"], enc)
            job.save(update_fields=["params"])
            if request.POST.get("action") == "resample":
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        existing = {t.name for t in ex.tables() if t.schema == "public"}
        names = []
        for i, lyr in enumerate(layers):
            lyr["selected"] = request.POST.get(f"sel_{i}") == "on"
            lyr["table"] = (request.POST.get(f"table_{i}") or lyr["table"]).strip().lower()
            lyr["mode"] = request.POST.get(f"mode_{i}", "create")
            lyr["to4326"] = request.POST.get(f"to4326_{i}") == "on"
            srid = request.POST.get(f"srid_{i}") or ""
            lyr["assign_srid"] = bool(srid) and (not lyr.get("srid") or int(srid) != lyr["srid"])
            lyr["srid"] = int(srid) if srid.isdigit() else lyr.get("srid")
            if not lyr["selected"]:
                continue
            if not gdal.TABLE_RE.match(lyr["table"]):
                errors.append(f"نام جدول «{lyr['table']}» مجاز نیست: فقط حروف کوچک انگلیسی، عدد و _، شروع با حرف.")
            elif lyr["table"] in names:
                errors.append(f"نام جدول «{lyr['table']}» دو بار انتخاب شده است.")
            elif lyr["table"] in existing and lyr["mode"] == "create":
                errors.append(f"جدول «{lyr['table']}» از قبل وجود دارد؛ نام دیگری بدهید یا «جایگزینی» یا «افزودن» را انتخاب کنید.")
            if lyr["geom_type"] and not lyr["srid"]:
                errors.append(f"سیستم مختصات لایه «{lyr['name']}» مشخص نیست؛ آن را انتخاب کنید.")
            names.append(lyr["table"])
        if not names:
            errors.append("حداقل یک لایه را انتخاب کنید.")
        job.params["layers"] = layers
        if errors:
            job.save(update_fields=["params"])
        else:
            job.status = Job.Status.QUEUED
            job.created_at = timezone.now()
            job.save(update_fields=["params", "status", "created_at"])
            messages.success(request, "ورود فایل در صف قرار گرفت.")
            return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    known = {code for code, _ in gdal.SRID_CHOICES}
    for lyr in layers:
        lyr["srid_in_list"] = lyr.get("srid") in known
    return render(request, "databases/import_review.html", {
        "db": db, "tables": ex.tables(), "section": "import", "job": job, "layers": layers, "errors": errors,
        "srid_choices": gdal.SRID_CHOICES})



# ---------------------------------------------------------------------- تیم و کاربران پایگاه داده
SESSION_ROLE_PW = "gp_role_pw_{}"


@site_user_required
@require_http_methods(["GET", "POST"])
def team_page(request, pk):
    from . import team
    from .models import DbRole, Member

    db = _user_db(request, pk)
    if request.method == "POST":
        action = request.POST.get("action", "")
        try:
            if action == "invite":
                m = team.invite(db, request.user, request.POST.get("phone", ""), request.POST.get("role", "viewer"))
                messages.success(request, f"{m.phone} با نقش {m.get_role_display()} اضافه شد."
                                 + ("" if m.user_id else " وقتی با همین شماره وارد سایت شود، پایگاه داده را می‌بیند."))
            elif action == "remove":
                team.remove_member(db, request.user, get_object_or_404(Member, pk=request.POST.get("id"), database=db))
                messages.success(request, "عضو حذف شد.")
            elif action == "role_create":
                pw = generate_password()
                role = team.create_role(db, request.user, request.POST.get("suffix", ""),
                                        request.POST.get("access", "read"), pw, request.POST.get("note", ""))
                request.session[SESSION_ROLE_PW.format(db.pk)] = {"name": role.name, "password": pw}
            elif action == "role_password":
                role = get_object_or_404(DbRole, pk=request.POST.get("id"), database=db)
                pw = generate_password()
                team.reset_role_password(db, request.user, role, pw)
                request.session[SESSION_ROLE_PW.format(db.pk)] = {"name": role.name, "password": pw}
            elif action == "role_drop":
                team.drop_role(db, request.user, get_object_or_404(DbRole, pk=request.POST.get("id"), database=db))
                messages.success(request, "کاربر حذف شد و اتصال‌هایش قطع شد.")
        except team.TeamError as exc:
            messages.error(request, str(exc))
        except ProvisionError as exc:
            messages.error(request, f"عملیات روی سرور ناموفق بود: {exc}")
        return redirect("databases:team", pk=db.pk)
    return render(request, "databases/team.html", {
        "db": db, "members": db.members.select_related("user"), "roles": db.db_roles.all(),
        "new_pw": request.session.pop(SESSION_ROLE_PW.format(db.pk), None),
        "role_prefix": team.role_name_for(db, ""),
    })
