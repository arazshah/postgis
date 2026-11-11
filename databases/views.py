import csv
import json
import time

from django.conf import settings
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse, StreamingHttpResponse
from django.middleware.csrf import get_token
from django.shortcuts import get_object_or_404, redirect, render
from django.templatetags.static import static
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required
from core.models import SiteSettings

from . import csvgeo, editor, importinto, services, tablealter, tablebuilder
from .crypto import generate_password
from .editor import EDIT_TTL, EditError, Editor
from .explorer import EXPORT_LIMIT, MAP_LIMIT, SQL_MAX_ROWS, Explorer, ExplorerError
from .forms import AddExtensionForm, CreateDatabaseForm, DeleteConfirmForm, PasswordResetForm
from .models import EditBatch, UserDatabase
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
    dbs = list(dbs)
    from jobs.models import Job

    last = {}
    for j in Job.objects.filter(database__in=dbs, kind=Job.Kind.BACKUP, status=Job.Status.DONE).order_by("-created_at"):
        last.setdefault(j.database_id, j)
    for d in dbs:
        d.last_backup = last.get(d.pk)
        d.alerts = _db_alerts(d)
        levels = {a["level"] for a in d.alerts}
        d.worst = "bad" if "bad" in levels else "warn" if "warn" in levels else "info" if levels else ""
        d.attn = 2 if d.worst == "bad" else 1 if d.worst == "warn" else 0  # برای فیلتر و مرتب‌سازی فهرست
    stats = {"count": len(dbs), "size": sum(d.size_bytes or 0 for d in dbs),
             "quota": sum(d.plan.quota_bytes for d in dbs if getattr(d.plan, "quota_bytes", None)),
             "running": Job.objects.filter(database__in=dbs, status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).count(),
             "backups": sum(1 for d in dbs if d.last_backup)}
    from classroom.services import teacher_contracts

    is_teacher = teacher_contracts(request.user).exists() or request.user.taught_classes.exists()
    can_create, reason = services.user_can_create(request.user)
    from billing.services import unused_vouchers

    return render(request, "databases/dashboard.html", {"dbs": dbs, "shared": shared, "can_create": can_create, "stats": stats,
                                                        "is_teacher": is_teacher,
                                                        "reason": reason,
                                                        "vouchers": unused_vouchers(request.user),
                                                        **_home(request.user, dbs, stats)})


def _greeting(now=None) -> str:
    h = timezone.localtime(now).hour
    return "صبح بخیر" if 5 <= h < 12 else "ظهر بخیر" if 12 <= h < 16 else "عصر بخیر" if 16 <= h < 20 else "شب بخیر"


def _home(user, dbs, stats) -> dict:
    """داده‌ی «خانه»: خوشامد، شمار پایگاه‌های نیازمند توجه، ادامه‌ی کار و چک‌لیست شروع. چند پرس‌وجوی تجمیعی، نه یکی برای هر پایگاه."""
    from analysis.models import LlmConfig, Question, ToolRun
    from jobs.models import Job
    from maps.models import WebMap
    from tools.catalog import info

    tool_info = info()

    live = [d for d in dbs if d.is_live]
    attn_count = sum(1 for d in dbs if d.attn)

    feed = []
    if dbs:
        for q in Question.objects.filter(database__in=dbs).select_related("database").order_by("-created_at")[:4]:
            feed.append({"icon": "spark", "kind": "پرسش فارسی", "text": q.text, "db": q.database.db_name, "when": q.created_at,
                         "url": reverse("analysis:page", args=[q.database_id]) + "#history"})
        for t in ToolRun.objects.filter(database__in=dbs).select_related("database").order_by("-created_at")[:4]:
            info = tool_info.get(t.tool)
            feed.append({"icon": "toolbox", "kind": "ابزار تحلیل", "text": getattr(info, "title", t.tool) + (f" — {t.summary}" if t.summary else ""),
                         "db": t.database.db_name, "when": t.created_at, "url": reverse("tools:page", args=[t.database_id])})
        for m in WebMap.objects.filter(database__in=dbs).select_related("database").order_by("-updated_at")[:4]:
            feed.append({"icon": "globe", "kind": "نقشه", "text": m.title, "db": m.database.db_name, "when": m.updated_at,
                         "url": reverse("maps:composer", args=[m.database_id, m.pk])})
        for j in Job.objects.filter(database__in=dbs, status=Job.Status.DONE,
                                    kind__in=[Job.Kind.IMPORT, Job.Kind.BACKUP]).select_related("database").order_by("-created_at")[:4]:
            feed.append({"icon": "upload" if j.kind == Job.Kind.IMPORT else "save", "kind": j.get_kind_display(),
                         "text": j.get_kind_display() + " انجام شد", "db": j.database.db_name, "when": j.created_at,
                         "url": reverse("databases:explore" if j.kind == Job.Kind.IMPORT else "databases:backups", args=[j.database_id])})
    feed.sort(key=lambda f: f["when"], reverse=True)

    target = live[0] if live else None
    has_llm = LlmConfig.objects.filter(user=user).exists()
    has_data = bool(dbs) and Job.objects.filter(database__in=dbs, kind=Job.Kind.IMPORT, status=Job.Status.DONE).exists()
    has_map = bool(dbs) and WebMap.objects.filter(database__in=dbs).exists()
    steps = [
        {"label": "پروفایل را کامل کنید", "hint": "نام و دانشگاه / شرکت", "done": bool(user.full_name and user.organization),
         "url": reverse("accounts:profile"), "icon": "user"},
        {"label": "پایگاه داده بسازید", "hint": "کمتر از یک دقیقه", "done": bool(dbs), "url": reverse("databases:create"), "icon": "db"},
        {"label": "اولین داده را وارد کنید", "hint": "فایل مکانی آپلود کنید",
         "done": has_data, "url": reverse("databases:import", args=[target.pk]) if target else "", "icon": "upload"},
        {"label": "اولین نقشه را بسازید", "hint": "لایه‌ها را روی نقشه ببینید",
         "done": has_map, "url": reverse("maps:index", args=[target.pk]) if target else "", "icon": "globe"},
        {"label": "مدل زبانی را وصل کنید", "hint": "برای پرسش فارسی", "done": has_llm,
         "url": reverse("accounts:profile") + "#ai", "icon": "spark"},
    ]
    done = sum(1 for s in steps if s["done"])
    quota = stats["quota"]
    return {"hello": _greeting(), "attn_count": attn_count, "feed": feed[:5], "steps": steps,
            "steps_done": done, "steps_pct": round(done * 100 / len(steps)),
            "onboarding": done < len(steps), "total_pct": min(100, round(stats["size"] * 100 / quota)) if quota else 0}


def _db_alerts(db) -> list[dict]:
    from core.templatetags.fa import fanum

    """نکته‌های «نیاز به توجه» برای کارت داشبورد؛ هر مورد یک جمله و یک اقدام روشن."""
    out = []
    if db.status == UserDatabase.Status.READONLY or db.usage_level == "full":
        out.append({"level": "bad", "text": "حجم پر شده و پایگاه داده فقط‌خواندنی است.", "cta": "ارتقای پلن", "url": reverse("billing:plans")})
    elif db.usage_level == "warn":
        out.append({"level": "warn", "text": f"{fanum(round(db.usage_percent))}٪ از حجم پر شده است.",
                    "cta": "بررسی مصرف", "url": reverse("databases:usage", args=[db.pk])})
    if db.status == UserDatabase.Status.EXPIRED:
        out.append({"level": "bad", "text": "اعتبار تمام شده؛ داده‌ها چند روز نگه داشته می‌شوند.", "cta": "تمدید", "url": reverse("billing:plans")})
    elif db.status == UserDatabase.Status.SUSPENDED:
        out.append({"level": "bad", "text": "این پایگاه داده معلق شده است.", "cta": "پشتیبانی", "url": reverse("support:new")})
    elif db.is_live and db.days_left is not None and db.days_left <= 7:
        out.append({"level": "warn", "text": f"فقط {fanum(db.days_left)} روز تا پایان اعتبار مانده است.", "cta": "تمدید", "url": reverse("billing:plans")})
    if db.is_live and not getattr(db, "last_backup", None):
        out.append({"level": "info", "text": "هنوز بکاپی نگرفته‌اید.", "cta": "گرفتن بکاپ", "url": reverse("databases:backups", args=[db.pk])})
    return out


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
            from analytics import services as analytics

            analytics.record(request, "db_created", plan=plan.slug if plan else "")
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


def _first_steps(db) -> str:
    """پایگاه تازه خالی است؛ تا اولین ورود داده موفق، صفحه‌ی نمای کلی راه بعدی را نشان می‌دهد.

    خروجی: "" (کارت لازم نیست)، "start" (هنوز داده‌ای نیامده) یا "running" (ورود در صف یا در حال اجراست).
    """
    from jobs.models import Job

    if not db.is_live:
        return ""
    jobs = db.jobs.filter(kind__in=[Job.Kind.IMPORT, Job.Kind.OSM_IMPORT])
    if jobs.filter(status=Job.Status.DONE).exists():
        return ""
    return "running" if jobs.filter(status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists() else "start"


@site_user_required
def detail(request, pk):
    db = _user_db(request, pk, "viewer")
    if not db.is_mine:
        return render(request, "databases/shared.html", {"db": db})
    once_password = request.session.pop(SESSION_PW_KEY.format(db.pk), None)
    return render(request, "databases/detail.html", {
        "db": db,
        "once_password": once_password,
        "first_steps": _first_steps(db),
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
    from jobs import offsite

    job = get_object_or_404(db.jobs, pk=job_id)
    if not job.downloadable:
        raise Http404
    path = offsite.ensure_local(job)  # اگر فایل محلی گم شده باشد، از نسخه‌ی ابری برمی‌گردد
    if path is None:
        raise Http404
    return FileResponse(path.open("rb"), as_attachment=True, filename=path.name,
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
    biggest = max((t.size_bytes for t in tables), default=0) or 1
    for t in tables:
        t.mappable = any(not g["geography"] and g["srid"] for g in t.geometry)
        t.size_pct = round(t.size_bytes * 100 / biggest) if t.size_bytes else 0
    schemas = sorted({t.schema for t in tables})
    ctx = {"db": db, "tables": tables, "section": "tables", "spatial_count": sum(t.mappable for t in tables),
           "geo_count": sum(1 for t in tables if t.geometry), "view_count": sum(1 for t in tables if t.kind in "vmf"),
           "total_size": sum(t.size_bytes for t in tables), "schemas": schemas if len(schemas) > 1 else []}
    if db.can_edit and db.status == db.Status.ACTIVE:
        ctx["builder_cfg"] = _builder_config(request, db, ex)
    return render(request, "databases/explore.html", ctx)


@site_user_required
def tables_json(request, pk):
    """فهرست جدول‌ها برای جست‌وجوی سریع Ctrl+K (بارگذاری تنبل، فقط هنگام باز شدن پالت)."""
    db, ex = _explorer_db(request, pk)
    if ex is None:
        return JsonResponse({"items": []})
    try:
        tables = ex.tables()
    except ExplorerError:
        return JsonResponse({"items": []})
    return JsonResponse({"items": [
        {"t": (f"{x.schema}." if x.schema != "public" else "") + x.name,
         "u": reverse("databases:explore_table", args=[db.pk, x.schema, x.name]),
         "g": "جدول" + (" مکانی" if x.geometry else ""), "k": "t"} for x in tables]})


def _builder_config(request, db, ex) -> dict:
    try:
        schemas = ex.writable_schemas() or ["public"]
    except ExplorerError:
        schemas = ["public"]
    return {**tablebuilder.client_config(), "schemas": schemas, "csrf": get_token(request),
            "urls": {"preview": reverse("databases:table_preview", args=[db.pk]),
                     "create": reverse("databases:table_new", args=[db.pk]),
                     "srid": reverse("databases:table_srid", args=[db.pk])}}


def _builder_json(view):
    def wrapper(request, pk):
        try:
            return view(request, pk)
        except (tablebuilder.BuildError, EditError, ExplorerError) as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    wrapper.__name__ = view.__name__
    return site_user_required(wrapper)


def _builder_guard(request, pk):
    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        raise ExplorerError("مرورگر فقط برای پایگاه داده فعال در دسترس است.")
    if db.status != db.Status.ACTIVE:
        raise ExplorerError("پایگاه داده فقط‌خواندنی یا غیرفعال است؛ ساخت جدول ممکن نیست.")
    return db, ex


@_builder_json
@require_POST
def table_preview(request, pk):
    _builder_guard(request, pk)
    plan = tablebuilder.build(_body(request).get("spec"))
    return JsonResponse({"ok": True, "sql": plan.script()})


@_builder_json
@require_POST
def table_new(request, pk):
    db, ex = _builder_guard(request, pk)
    if db.size_bytes >= db.quota_bytes:
        raise ExplorerError("سهمیه‌ی حجم پایگاه داده پر شده است؛ پلن را ارتقا دهید یا داده‌های اضافه را حذف کنید.")
    plan = tablebuilder.build(_body(request).get("spec"))
    spec = plan.spec
    if spec["schema"] not in ex.writable_schemas():
        raise ExplorerError("اجازه ساخت جدول در این schema را ندارید.")
    ex.create_table(plan)
    qualified = f"{spec['schema']}.{spec['name']}"
    services.logevent("table_create", f"جدول {qualified} ساخته شد ({len(spec['columns'])} ستون)",
                      user=request.user, database=db)
    return JsonResponse({"ok": True, "url": reverse("databases:explore_table",
                                                    args=[db.pk, spec["schema"], spec["name"]])})


@_builder_json
def table_srid(request, pk):
    _, ex = _builder_guard(request, pk)
    return JsonResponse({"ok": True, "items": ex.search_srid(request.GET.get("q", ""))})


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
        editing = db.can_edit and db.status == db.Status.ACTIVE
        if editing:
            ctx["edit_cfg"] = _edit_config(request, db, ex, t)
        if tab == "columns":
            ctx["columns"] = ex.columns(t)
            ctx["indexes"] = ex.indexes(t)
            if editing and t.kind in editor.EDITABLE_KINDS:
                ctx["structure_cfg"] = _structure_config(request, db, t, ctx["columns"], ctx["indexes"])
        elif tab == "map":
            from maps.models import WebMap

            mappable = [x for x in tables if any(not g["geography"] and g["srid"] for g in x.geometry)]
            ctx["mappable"] = t in mappable
            if ctx["mappable"]:
                from analytics import services as analytics
                from analytics.models import Event

                analytics.record(request, Event.MAP_VIEWED)
            ctx["compare"] = len(mappable) > 1
            ctx["maps"] = list(WebMap.objects.filter(database=db).only("pk", "title")) if db.can_edit else []
        else:
            try:
                page = int(request.GET.get("page", "1"))
            except ValueError:
                page = 1
            ctx["data"] = ex.rows(t, page, with_keys=bool(editing and ctx["edit_cfg"]["capable"]))
            ctx["data"]["pairs"] = list(zip(ctx["data"]["rows"], ctx["data"]["keys"] or [None] * len(ctx["data"]["rows"]), strict=True))
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    return render(request, "databases/explore_table.html", ctx)


@site_user_required
@require_POST
def explore_drop(request, pk, schema, table):
    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    if db.status != db.Status.ACTIVE:
        messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است.")
        return redirect("databases:explore", pk=db.pk)
    try:
        t = ex.find(schema, table)
        if request.POST.get("confirm", "").strip() != t.name:
            messages.error(request, "برای حذف، نام جدول را دقیقاً وارد کنید.")
            return redirect("databases:explore_table", pk=db.pk, schema=schema, table=table)
        ex.drop_table(t)
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:explore", pk=db.pk)
    # لایه‌ها و APIهای منتشرشده از این جدول دیگر معنا ندارند
    from maps.models import MapLayer
    from publish.models import Layer
    from restapi.models import ApiTable

    MapLayer.objects.filter(webmap__database=db, schema=schema, table=table).delete()
    gone = Layer.objects.filter(service__database=db, schema=schema, table=table).delete()[0]
    gone += ApiTable.objects.filter(service__database=db, schema=schema, table=table).delete()[0]
    messages.success(request, f"جدول {table} حذف شد." + (" انتشار آن هم برداشته شد." if gone else ""))
    return redirect("databases:explore", pk=db.pk)


@site_user_required
def explore_geojson(request, pk, schema, table):
    db, ex = _explorer_db(request, pk)
    if ex is None:
        raise Http404
    try:
        t = ex.find(schema, table)
        download = request.GET.get("download") == "1"
        keys = request.GET.get("keys") == "1" and db.can_edit
        data = ex.geojson(t, request.GET.get("column"), limit=EXPORT_LIMIT if download else MAP_LIMIT, with_keys=keys)
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
    from . import nl2sql

    query = request.POST.get("query", "") if request.method == "POST" else request.GET.get("q", "")
    allow_write = request.POST.get("allow_write") == "on" and db.can_edit
    result = error = created = None
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
    made = nl2sql.created_table(query) if result else None
    if made:
        created = next((t for t in tables if (t.schema, t.name) == made), None)
    # پرسش فارسی‌ای که این SQL از آن ساخته شد، تا بعد از اجرا هم دیده شود
    nl = {"text": request.POST.get("nl_text", "")[:nl2sql.MAX_TEXT],
          "note": request.POST.get("nl_note", "")[:800]} if request.method == "POST" else {"text": "", "note": ""}
    return render(request, "databases/explore_sql.html", {
        "db": db, "tables": tables, "query": query, "allow_write": allow_write, "result": result,
        "error": error, "section": "sql", "max_rows": SQL_MAX_ROWS, "created": created, "nl": nl,
        "llm_cfg": nl2sql.user_config(request.user), "nl_examples": _nl_examples(tables),
        "can_why": bool(result and result["columns"] and not result["rows"] and nl2sql.classify(query) == "read"),
        "mode": "nl" if request.GET.get("mode") == "nl" else ("nl" if nl["text"] and not query else "sql")})


def _nl_examples(tables) -> list[str]:
    """نمونه پرسش فارسی بر اساس جدول‌های همین پایگاه."""
    polys = [t for t in tables if t.geometry and "POLYGON" in (t.geometry[0]["type"] or "").upper()]
    points = [t for t in tables if t.geometry and "POINT" in (t.geometry[0]["type"] or "").upper()]
    out = []
    if tables:
        out.append(f"در جدول {tables[0].name} چند ردیف هست؟")
    if polys and points:
        out.append(f"نقاط {points[0].name} که داخل {polys[0].name} هستند را در یک لایه جدید ذخیره کن")
    if polys:
        out.append(f"مساحت هر عارضه {polys[0].name} را به متر مربع حساب کن و از بزرگ به کوچک مرتب کن")
    if points:
        out.append(f"تعداد نقاط {points[0].name} را به تفکیک یک ستون متنی بشمار")
    return out[:4]


@site_user_required
@require_POST
def explore_sql_ask(request, pk):
    """متن فارسی ← یک دستور SQL (JSON). اجرا با همان کنسول و همان محافظ‌هاست."""
    from . import nl2sql

    db, ex = _explorer_db(request, pk)
    if ex is None:
        return JsonResponse({"ok": False, "error": "مرورگر فقط برای پایگاه داده فعال در دسترس است."}, status=400)
    try:
        draft = nl2sql.generate(db, request.user, request.POST.get("text", ""),
                                share_values=request.POST.get("share_values") == "on")
    except nl2sql.NLError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    data = draft.as_dict()
    data["can_write"] = db.can_edit
    # فقط پرس‌وجوی خواندنیِ سالم بی‌درنگ اجرا می‌شود؛ هر تغییری را کاربر خودش تأیید می‌کند
    data["auto_run"] = draft.valid and not draft.writes
    return JsonResponse({"ok": True, **data})


@site_user_required
@require_POST
def explore_sql_why(request, pk):
    """پرس‌وجوی خواندنی بی‌نتیجه: دلیل احتمالی و کوئری اصلاح‌شده (JSON)."""
    from . import nl2sql

    db, ex = _explorer_db(request, pk)
    if ex is None:
        return JsonResponse({"ok": False, "error": "مرورگر فقط برای پایگاه داده فعال در دسترس است."}, status=400)
    try:
        data = nl2sql.diagnose_empty(db, request.user, request.POST.get("query", ""), request.POST.get("text", ""))
    except nl2sql.NLError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **data})


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


def _health_context(tables, issues) -> dict:
    """مشکل‌ها را یک‌بار بر اساس نوع و یک‌بار بر اساس جدول گروه می‌کند و شمارنده‌ها را می‌سازد."""
    from collections import OrderedDict

    for i in issues:
        i["qualified"] = i["table"] if i["schema"] == "public" else f"{i['schema']}.{i['table']}"
        i["label"] = Explorer.FIXES.get(i["fix"], "")
    by_fix = OrderedDict((k, []) for k in Explorer.FIX_INFO)
    by_table = OrderedDict()
    for i in issues:
        by_fix.setdefault(i["fix"], []).append(i)
        by_table.setdefault((i["schema"], i["table"]), []).append(i)
    problems = []
    for fix, items in by_fix.items():
        if not items:
            continue
        title, why = Explorer.FIX_INFO.get(fix, (fix, ""))
        level = min((i["level"] for i in items), key=lambda x: Explorer.LEVEL_RANK.get(x, 9))
        problems.append({"fix": fix, "title": title, "why": why, "level": level, "items": items,
                         "tables": len({(i["schema"], i["table"]) for i in items}), "bulk": fix != "set_srid"})
    problems.sort(key=lambda g: Explorer.LEVEL_RANK.get(g["level"], 9))
    bad_tables = [{"schema": s, "table": t, "qualified": v[0]["qualified"], "items": v,
                   "level": min((i["level"] for i in v), key=lambda x: Explorer.LEVEL_RANK.get(x, 9))}
                  for (s, t), v in by_table.items()]
    bad_tables.sort(key=lambda g: (Explorer.LEVEL_RANK.get(g["level"], 9), g["qualified"]))
    count = lambda lv: sum(1 for i in issues if i["level"] == lv)  # noqa: E731
    checked = sum(1 for t in tables if t.kind in ("r", "p"))
    return {"problems": problems, "bad_tables": bad_tables, "n_error": count("error"), "n_warning": count("warning"),
            "n_info": count("info"), "n_healthy": max(checked - len(by_table), 0),
            "n_auto": sum(1 for i in issues if i["fix"] != "set_srid")}


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
                if request.POST.get("fix") == "group":
                    done, failed = ex.fix_group(request.POST.get("kind", ""))
                    if done:
                        messages.success(request, f"{len(done)} مورد اصلاح شد.".translate(_FA))
                    for f in failed:
                        messages.error(request, f)
                    return redirect("databases:explore_health", pk=db.pk)
                if request.POST.get("fix") == "all":
                    done, failed = ex.fix_all()
                    if done:
                        messages.success(request, f"{len(done)} مورد اصلاح شد.".translate(_FA))
                    for f in failed:
                        messages.error(request, f)
                    return redirect("databases:explore_health", pk=db.pk)
                srid = int(request.POST.get("srid") or request.POST.get("srid_other") or 0) or None
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
        "srid_common": SRID_CHOICES[:1] + [c for c in SRID_CHOICES if c[0] in (32639, 3857)],
        "srid_other": [c for c in SRID_CHOICES if c[0] not in (4326, 32639, 3857)],
        **_health_context(tables, issues)})


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
    into_ref = (request.POST.get("into") or request.GET.get("into") or "").strip()
    into = None
    if into_ref:
        try:
            schema, _, name = into_ref.partition(".")
            into = ex.find(schema, name)
            if into.kind not in editor.EDITABLE_KINDS:
                raise ExplorerError("فقط در جدول معمولی می‌شود داده وارد کرد (نه نما).")
        except ExplorerError as exc:
            into, error = None, str(exc)
            messages.error(request, str(exc))
            return redirect("databases:explore", pk=db.pk)
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
        elif f.size * (2.6 if into else 1.3) > free:
            error = "فضای خالی پایگاه داده برای این فایل کافی نیست. پلن را ارتقا دهید یا داده‌های اضافه را حذف کنید."
        else:
            job = Job.objects.create(kind=Job.Kind.IMPORT, status=Job.Status.DRAFT, database=db, user=request.user,
                                     params={"file": f"upload{ext}", "original": f.name[:200]})
            folder = import_dir(job)
            folder.mkdir(parents=True, exist_ok=True)
            with open(folder / f"upload{ext}", "wb") as out:
                for chunk in f.chunks():
                    out.write(chunk)
            existing = {t.name for t in ex.tables() if t.schema == "public"}
            try:
                if ext == ".csv":
                    info = _csv_start(job, folder, existing)
                else:
                    info = gdal.inspect(folder / f"upload{ext}")
            except (gdal.GdalError, ValueError) as exc:
                shutil.rmtree(folder, ignore_errors=True)
                job.delete()
                error = f"فایل خوانده نشد: {exc}"
            else:
                for lyr in info["layers"]:
                    if ext == ".csv":
                        continue  # لایه CSV در _csv_start کامل ساخته شده است
                    lyr["selected"] = bool(lyr["geom_type"] or ext == ".csv")
                    lyr["exists"] = lyr["table"] in existing
                    lyr["mode"] = "create"
                    lyr["to4326"] = False
                job.params = {**job.params, **info}
                if into:
                    _into_init(job, ex, into)
                job.save(update_fields=["params"])
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    recent = db.jobs.filter(kind="import").exclude(status="draft")[:10]
    return render(request, "databases/import.html", {
        "db": db, "tables": ex.tables(), "section": "import", "error": error, "max_mb": max_mb,
        "accept": ",".join(sorted(gdal.ALLOWED_EXT)), "recent": recent, "into": into})


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
        if request.POST.get("action") == "pick" and job.params.get("into"):
            # لایه‌ی دیگری از فایل انتخاب شد: نگاشت خودکار از نو ساخته می‌شود
            try:
                idx = int(request.POST.get("layer_into", "0"))
            except ValueError:
                idx = 0
            idx = idx if 0 <= idx < len(layers) else 0
            for i, lyr in enumerate(layers):
                lyr["selected"] = i == idx
            job.params["layers"] = layers
            job.params["into_map"] = importinto.auto_map(ex.columns(_into_table(ex, job)), layers[idx].get("fields", []))
            job.save(update_fields=["params"])
            return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        enc = request.POST.get("encoding") or None
        if job.params.get("csv"):
            try:
                errors += _csv_update(job, request.POST, enc, {t.name for t in ex.tables() if t.schema == "public"})
            except (gdal.GdalError, ValueError) as exc:
                errors.append(f"فایل با این تنظیمات خوانده نشد: {exc}")
            layers = job.params["layers"]
            if request.POST.get("action") == "resample" and not errors:
                job.save(update_fields=["params"])
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        elif job.params.get("encoding") and enc in ("UTF-8", "CP1256") and enc != job.params["encoding"]:
            job.params["encoding"] = enc
            path = import_dir(job) / job.params["file"]
            for lyr in layers:
                lyr["sample"] = gdal.sample(path, lyr["name"], enc)
            job.save(update_fields=["params"])
            if request.POST.get("action") == "resample":
                return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
        into = job.params.get("into")
        if into:
            names = _into_post(request.POST, job, ex, layers, errors)
        else:
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
                if "csv_bad" in lyr:
                    errors += _csv_checks(lyr)
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
            from analytics import services as analytics
            from analytics.models import Event

            analytics.record(request, Event.IMPORT_QUEUED, ext=str(job.params.get("file", "")).rsplit(".", 1)[-1])
            messages.success(request, "ورود فایل در صف قرار گرفت.")
            return redirect("databases:import_review", pk=db.pk, job_id=job.pk)
    known = {code for code, _ in gdal.SRID_CHOICES}
    for lyr in layers:
        lyr["srid_in_list"] = lyr.get("srid") in known
        if "csv_bad" in lyr:
            lyr["csv_warn"] = csvgeo.range_check(lyr.get("csv_stats") or {}, lyr.get("srid"))[1]
    csv_info = job.params.get("csv")
    into_ctx = _into_context(ex, job, layers) if job.params.get("into") else None
    return render(request, "databases/import_review.html", {
        "db": db, "tables": ex.tables(), "section": "import", "job": job, "layers": layers, "errors": errors,
        "into": into_ctx,
        "srid_choices": gdal.SRID_CHOICES, "csv": csv_info, "csv_modes": CSV_MODES,
        "csv_encodings": list(csvgeo.ENCODINGS)})


# ---------------------------------------------------------------------- تغییر ساختار جدول (ستون، ایندکس، SRID)
def _table_usage(db, t) -> dict:
    """لایه‌ها و APIهای منتشرشده یا نقشه‌هایی که از این جدول استفاده می‌کنند (برای هشدار قبل از تغییر ساختار)."""
    from maps.models import MapLayer
    from publish.models import Layer
    from restapi.models import ApiTable

    return {"maps": MapLayer.objects.filter(webmap__database=db, schema=t.schema, table=t.name).count(),
            "published": Layer.objects.filter(service__database=db, schema=t.schema, table=t.name).count(),
            "api": ApiTable.objects.filter(service__database=db, schema=t.schema, table=t.name).count()}


def _structure_config(request, db, t, cols, indexes) -> dict:
    cfg = tablebuilder.client_config()
    geo = next(iter(t.geometry), None)
    return {
        "csrf": get_token(request), "url": reverse("databases:table_structure", args=[db.pk, t.schema, t.name]),
        "table": t.name, "schema": t.schema, "types": cfg["types"], "geometry_types": cfg["geometry_types"],
        "columns": [{"name": c["name"], "type": c["type"], "base": c["base"], "pk": c["pk"], "spatial": c["spatial"],
                     "not_null": c["not_null"], "default": c["default"], "identity": c["identity"],
                     "generated": c["generated"]} for c in cols],
        "indexes": [{"name": i["name"], "columns": i["columns"], "unique": i["unique"]} for i in indexes],
        "geometry": geo, "usage": _table_usage(db, t),
    }


@site_user_required
@require_POST
def table_structure(request, pk, schema, table):
    try:
        db, ex = _explorer_db(request, pk, "editor")
        if ex is None:
            raise ExplorerError("مرورگر فقط برای پایگاه داده فعال در دسترس است.")
        if db.status != db.Status.ACTIVE:
            raise ExplorerError("پایگاه داده فقط‌خواندنی یا غیرفعال است؛ تغییر ساختار ممکن نیست.")
        t = ex.find(schema, table)
        if t.kind not in editor.EDITABLE_KINDS:
            raise ExplorerError("ساختار نما یا جدول خارجی از این‌جا تغییر نمی‌کند.")
        data = _body(request)
        plan = tablealter.build(t, ex.columns(t), ex.indexes(t), data.get("op"), data.get("params") or {})
        usage = _table_usage(db, t)
        if data.get("dry_run"):
            return JsonResponse({"ok": True, "sql": plan.script(), "summary": plan.summary, "danger": plan.danger,
                                 "usage": usage})
        if plan.danger and str(data.get("confirm", "")).strip() != plan.danger:
            raise ExplorerError(f"برای تأیید، «{plan.danger}» را دقیقاً بنویسید.")
        ex.alter_table(plan)
    except (tablebuilder.BuildError, EditError, ExplorerError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    if plan.touches_columns:
        EditBatch.objects.filter(database=db, schema=t.schema, table=t.name).delete()  # بازگردانی‌ها دیگر معنا ندارند
    final = plan.renamed_table or t.name
    if plan.renamed_table:
        from maps.models import MapLayer
        from publish.models import Layer
        from restapi.models import ApiTable

        MapLayer.objects.filter(webmap__database=db, schema=t.schema, table=t.name).update(table=final)
        Layer.objects.filter(service__database=db, schema=t.schema, table=t.name).update(table=final)
        ApiTable.objects.filter(service__database=db, schema=t.schema, table=t.name).update(table=final)
    services.logevent("table_alter", f"{t.qualified}: {plan.summary}", user=request.user, database=db)
    return JsonResponse({"ok": True, "url": reverse("databases:explore_table", args=[db.pk, t.schema, final]) + "?tab=columns"})


# ---------------------------------------------------------------------- ورود فایل به جدول موجود (نگاشت ستون‌ها)
def _into_init(job, ex, table) -> None:
    layers = job.params["layers"]
    pick = next((x for x in layers if x.get("geom_type")), layers[0])
    for x in layers:
        x["selected"] = x is pick
    job.params["into"] = {"schema": table.schema, "table": table.name}
    job.params["into_map"] = importinto.auto_map(ex.columns(table), pick.get("fields", []))
    job.params["into_mode"] = "append"


def _into_table(ex, job):
    into = job.params["into"]
    return ex.find(into["schema"], into["table"])


def _into_context(ex, job, layers) -> dict:
    t = _into_table(ex, job)
    cols = ex.columns(t)
    layer = next((x for x in layers if x.get("selected")), layers[0] if layers else {})
    fields = layer.get("fields", [])
    mapping = job.params.get("into_map") or {}
    sample = (layer.get("sample") or [{}])[0]
    rows = []
    for c in importinto.target_columns(cols):
        i = mapping.get(c["name"])
        src = fields[i] if isinstance(i, int) and 0 <= i < len(fields) else None
        rows.append({"col": c, "required": importinto.is_required(c), "src": i, "src_name": src,
                     "sample": "" if src is None else sample.get(src, "")})
    geo = next(iter(t.geometry), None)
    gcol = next((c for c in cols if geo and c["name"] == geo["column"]), None)
    compat = importinto.geom_compat(layer.get("geom_type") or "", (geo or {}).get("type") or "")
    return {"table": t, "rows": rows, "fields": list(enumerate(fields)), "geo": geo,
            "geo_required": bool(gcol and gcol["not_null"]), "geom_ok": compat,
            "mode": job.params.get("into_mode", "append"), "layer": layer, "count": layer.get("count"),
            "same_srid": bool(geo and layer.get("srid") and layer["srid"] == geo["srid"])}


def _into_post(post, job, ex, layers, errors) -> list:
    """فرم نگاشت ستون‌ها را اعتبارسنجی و در params ذخیره می‌کند؛ خطاها به errors اضافه می‌شوند."""
    t = _into_table(ex, job)
    cols = ex.columns(t)
    try:
        pick = int(post.get("layer_into", "0"))
    except ValueError:
        pick = 0
    pick = pick if 0 <= pick < len(layers) else 0
    for i, lyr in enumerate(layers):
        lyr["selected"] = i == pick
    lyr = layers[pick]
    srid = post.get(f"srid_{pick}") or ""
    lyr["assign_srid"] = bool(srid) and (not lyr.get("srid") or int(srid) != lyr["srid"])
    lyr["srid"] = int(srid) if srid.isdigit() else lyr.get("srid")
    fields = lyr.get("fields", [])
    mapping = {}
    for c in importinto.target_columns(cols):
        raw = post.get("map_" + c["name"], "")
        if raw == "":
            if importinto.is_required(c):
                errors.append(f"ستون «{c['name']}» الزامی است و مقدار پیش‌فرض ندارد؛ یک ستون فایل برایش انتخاب کنید.")
            continue
        if not raw.isdigit() or int(raw) >= len(fields):
            errors.append(f"ستون فایل برای «{c['name']}» نامعتبر است.")
            continue
        mapping[c["name"]] = int(raw)
    job.params["into_map"] = mapping
    mode = post.get("into_mode", "append")
    job.params["into_mode"] = mode if mode in ("append", "replace") else "append"
    geo = next(iter(t.geometry), None)
    if geo:
        if not lyr.get("geom_type"):
            gcol = next((c for c in cols if c["name"] == geo["column"]), None)
            if gcol and gcol["not_null"]:
                errors.append(f"ستون هندسه‌ی «{geo['column']}» الزامی است ولی این فایل هندسه ندارد.")
        else:
            if not lyr.get("srid"):
                errors.append("سیستم مختصات فایل مشخص نیست؛ آن را انتخاب کنید.")
            if not importinto.geom_compat(lyr.get("geom_type"), geo.get("type")):
                errors.append(f"نوع هندسه‌ی فایل ({lyr['geom_type']}) با ستون «{geo['column']}» ({geo['type']}) نمی‌خواند.")
    if not mapping and not (geo and lyr.get("geom_type")):
        errors.append("دست‌کم یک ستون را به ستونی از فایل وصل کنید.")
    if job.params["into_mode"] == "replace" and post.get("confirm", "").strip() != t.name:
        errors.append("برای جایگزینی کل داده‌ها، نام جدول را دقیقاً در کادر تأیید بنویسید.")
    if "csv_bad" in lyr:
        errors += _csv_checks(lyr)
    return [t.name]


# ---------------------------------------------------------------------- ورود CSV: ستون‌های مکانی
CSV_MODES = [
    ("xy", "دو ستون جدا: طول (X) و عرض (Y)"),
    ("pair", "یک ستون با هر دو مقدار (مثل «35.7, 51.4»)"),
    ("wkt", "ستون هندسه به‌صورت WKT"),
    ("none", "بدون مکان (فقط جدول)"),
]


def _csv_start(job, folder, existing: set) -> dict:
    """بعد از آپلود CSV: تحلیل، پیشنهاد ستون‌ها، بازنویسی و ساخت لایه."""
    src = folder / job.params["file"]
    job.params["source"] = job.params["file"]
    job.params["csv"] = csvgeo.analyze(src)
    lyr = _csv_refresh(job, folder, existing, None)
    return {"driver": "CSV", "encoding": job.params["csv"]["encoding"], "layers": [lyr]}


def _csv_refresh(job, folder, existing: set, prev: dict | None) -> dict:
    """فایل را با spec فعلی آماده می‌کند و لایه را می‌سازد؛ انتخاب‌های قبلی کاربر (نام جدول، حالت، SRID) حفظ می‌شود."""
    from . import gdal

    info = job.params["csv"]
    spec = info["spec"]
    dst = csvgeo.prepared_path(folder, job.params.get("original", ""))
    stats = csvgeo.prepare(folder / job.params["source"], dst, info["encoding"], info["delimiter"], spec)
    job.params["file"] = str(dst.relative_to(folder))
    lyr = gdal.inspect(dst)["layers"][0]
    lyr["sample"] = []  # برای CSV نمونه خام فایل در بخش ستون‌ها نمایش داده می‌شود
    guess = stats.get("srid") or spec.get("srid") or csvgeo.guess_srid(stats)
    keep_srid = prev and prev.get("srid") and prev.get("csv_mode") == spec["mode"]
    srid = prev["srid"] if keep_srid else guess
    if spec["mode"] == "none":
        srid = None
    lyr.update({
        "srid": srid, "selected": True, "mode": "create", "to4326": False,
        "csv_mode": spec["mode"], "csv_bad": stats["bad"], "csv_rows": stats["rows"],
        "csv_stats": {k: stats[k] for k in ("xmin", "xmax", "ymin", "ymax", "points")},
    })
    if prev:
        lyr.update({k: prev[k] for k in ("table", "mode", "to4326", "selected") if k in prev})
    lyr["exists"] = lyr["table"] in existing
    return lyr


def _csv_update(job, post, enc: str | None, existing: set) -> list[str]:
    """تغییر انکودینگ یا ستون‌های مکانی از فرم بررسی؛ فقط در صورت تغییر، فایل دوباره ساخته می‌شود."""
    from jobs.services import import_dir

    folder = import_dir(job)
    info = job.params["csv"]
    prev = (job.params.get("layers") or [None])[0]
    if enc in csvgeo.ENCODINGS and enc != info["encoding"]:
        # نام ستون‌ها با انکودینگ دیگر عوض می‌شود؛ تحلیل از نو
        job.params["csv"] = csvgeo.analyze(folder / job.params["source"], enc)
        job.params["encoding"] = enc
    else:
        spec, errors = csvgeo.clean_spec(info["columns"], {
            "mode": post.get("csv_mode"), "x": post.get("csv_x"), "y": post.get("csv_y"),
            "pair": post.get("csv_pair"), "pair_order": post.get("csv_pair_order"), "geom": post.get("csv_geom")})
        if errors:
            return errors
        if csvgeo.same_spec(spec, info["spec"]):
            return []
        info["spec"] = {**spec, "srid": None}
    job.params["layers"] = [_csv_refresh(job, folder, existing, prev)]
    return []


def _csv_checks(lyr: dict) -> list[str]:
    if lyr.get("csv_mode") == "none":
        return []
    if lyr.get("csv_rows") and lyr["csv_bad"] >= lyr["csv_rows"]:
        return ["در هیچ سطری مختصات قابل‌خواندن پیدا نشد. ستون‌های مکانی را درست انتخاب کنید یا «بدون مکان» را بزنید."]
    level, msg = csvgeo.range_check(lyr.get("csv_stats") or {}, lyr.get("srid"))
    return [msg] if level == "error" else []



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


# ---------------------------------------------------------------------- داشبورد مصرف
@site_user_required
@require_http_methods(["GET", "POST"])
def usage_page(request, pk):
    from . import usage

    db = _user_db(request, pk, "editor")
    if request.method == "POST":
        try:
            pid = int(request.POST.get("pid", "0"))
        except ValueError:
            pid = 0
        if pid and usage.cancel(db, pid):
            messages.success(request, "درخواست توقف کوئری فرستاده شد.")
        else:
            messages.error(request, "این کوئری پیدا نشد یا تمام شده است.")
        return redirect("databases:usage", pk=db.pk)
    stats, error = usage.safe_collect(db) if db.is_live else (None, "پایگاه داده فعال نیست.")
    hist = usage.history(db)
    reqs = usage.requests(db)
    return render(request, "databases/usage.html", {
        "db": db, "stats": stats, "error": error, "history": hist, "requests": reqs,
        "size_chart": _bars([h["size"] for h in hist], [h["day"] for h in hist], db.quota_bytes),
        "req_chart": _bars([r["n"] for r in reqs], [r["day"] for r in reqs], db.plan.publish_daily_requests),
    })


def _bars(values, days, cap=None, width=600, height=140):
    """نمودار ستونی ساده SVG (بدون کتابخانه): مقادیر و خط سقف."""
    if not values:
        return None
    top = max(max(values), 1)
    if cap and cap < top * 3:
        top = max(top, cap)
    n = len(values)
    gap = 4
    bw = max(2, (width - gap * (n - 1)) / n)
    bars = []
    from datetime import datetime, time

    for i, (v, d) in enumerate(zip(values, days, strict=True)):
        d = timezone.make_aware(datetime.combine(d, time(12)))  # فیلتر jdate تاریخ‌وزمان می‌خواهد
        h = 0 if not v else max(2, round(v / top * (height - 6)))
        bars.append({"x": round(i * (bw + gap), 1), "y": height - h, "w": round(bw, 1), "h": h, "v": v, "day": d})
    cap_y = round(height - cap / top * (height - 6), 1) if cap and cap <= top else None
    return {"bars": bars, "w": width, "h": height, "cap_y": cap_y}


# ---------------------------------------------------------------------- ویرایش جدول (حالت ویرایش)
def _edit_key(db) -> str:
    return f"gp_edit_until_{db.pk}"


def _edit_active(request, db) -> bool:
    return request.session.get(_edit_key(db), 0) > time.time()


def _edit_config(request, db, ex, t) -> dict:
    """تنظیمات و فراداده‌ی ویرایش که جاوااسکریپت صفحه لازم دارد."""
    cols = ex.columns(t)
    cap = editor.edit_capability(t, cols)
    writable = editor.editable_columns(cols)
    args = [db.pk, t.schema, t.name]
    last = (EditBatch.objects.filter(database=db, schema=t.schema, table=t.name, undone_at__isnull=True).first()
            if cap["ok"] else None)
    return {
        "capable": cap["ok"], "reason": cap["reason"], "active": cap["ok"] and _edit_active(request, db),
        "csrf": get_token(request), "ttl": EDIT_TTL, "key": f"gp-edit-{db.pk}-{t.schema}.{t.name}", "table": t.qualified,
        "pk": [c["name"] for c in cols if c["pk"]],
        "columns": [{"name": c["name"], "type": c["type"], "base": c["base"], "not_null": c["not_null"],
                     "default": c["default"], "pk": c["pk"], "spatial": c["spatial"],
                     "writable": c["name"] in writable, "identity": c["identity"], "generated": c["generated"]}
                    for c in cols],
        "geometry": t.geometry,
        "tiles": SiteSettings.get().map_tile_url, "attr": SiteSettings.get().map_tile_attribution,
        "vendor": {"leaflet_js": static("vendor/leaflet/leaflet.js"), "leaflet_css": static("vendor/leaflet/leaflet.css"),
                   "pm_js": static("vendor/leaflet-geoman/leaflet-geoman.min.js"),
                   "pm_css": static("vendor/leaflet-geoman/leaflet-geoman.css")},
        "urls": {k: reverse(f"databases:explore_edit_{k}", args=args) for k in ("mode", "row", "apply", "undo")},
        "geojson": reverse("databases:explore_geojson", args=args) + "?keys=1",
        "last": ({"id": last.pk, "inserted": last.inserted, "updated": last.updated, "deleted": last.deleted,
                  "at": timezone.localtime(last.created_at).strftime("%H:%M")} if last else None),
    }


def _body(request) -> dict:
    if len(request.body) > 8 * 1024 * 1024:
        raise EditError("حجم تغییرها بیش از حد است.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise EditError("درخواست نامعتبر است.") from exc
    if not isinstance(data, dict):
        raise EditError("درخواست نامعتبر است.")
    return data


def _edit_guard(request, pk, schema, table, need_mode: bool = True):
    """دسترسی ویرایشگر، پایگاه داده‌ی فعال، جدول قابل‌ویرایش و (در صورت نیاز) روشن‌بودن حالت ویرایش."""
    db = _user_db(request, pk, "editor")
    if not db.is_live or db.status != db.Status.ACTIVE:
        raise EditError("پایگاه داده فعال نیست یا فقط‌خواندنی است؛ ویرایش ممکن نیست.")
    ex = Explorer(db)
    t = ex.find(schema, table)
    if need_mode and not _edit_active(request, db):
        raise EditError("حالت ویرایش خاموش یا منقضی شده است. دوباره آن را روشن کنید.")
    return db, ex, t


def _edit_json(view):
    def wrapper(request, pk, schema, table):
        try:
            return view(request, pk, schema, table)
        except EditError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
        except ExplorerError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    wrapper.__name__ = view.__name__
    return site_user_required(wrapper)


@_edit_json
@require_POST
def explore_edit_mode(request, pk, schema, table):
    on = bool(_body(request).get("on"))
    db, ex, t = _edit_guard(request, pk, schema, table, need_mode=False)
    if on:
        cap = editor.edit_capability(t, ex.columns(t))
        if not cap["ok"]:
            raise EditError(cap["reason"])
        request.session[_edit_key(db)] = time.time() + EDIT_TTL
        services.logevent("edit_mode_on", f"حالت ویرایش روشن شد: {t.qualified}", user=request.user, database=db)
    else:
        request.session.pop(_edit_key(db), None)
    return JsonResponse({"ok": True, "on": on, "ttl": EDIT_TTL})


@_edit_json
def explore_edit_row(request, pk, schema, table):
    db, ex, t = _edit_guard(request, pk, schema, table)
    try:
        key = json.loads(request.GET.get("pk", ""))
    except ValueError as exc:
        raise EditError("کلید سطر نامعتبر است.") from exc
    return JsonResponse({"ok": True, **Editor(ex).row(t, key)})


@_edit_json
@require_POST
def explore_edit_apply(request, pk, schema, table):
    data = _body(request)
    db, ex, t = _edit_guard(request, pk, schema, table)
    dry = bool(data.get("dry_run"))
    out = Editor(ex).apply(t, data.get("changes"), dry_run=dry, repair=bool(data.get("repair")))
    request.session[_edit_key(db)] = time.time() + EDIT_TTL  # کار فعال، مهلت را تمدید می‌کند
    resp = {"ok": out["ok"], "results": out["results"], "counts": out["counts"], "dry_run": dry}
    if out["ok"] and not dry:
        c = out["counts"]
        batch = EditBatch.objects.create(database=db, user=request.user, schema=t.schema, table=t.name,
                                         inserted=c["insert"], updated=c["update"], deleted=c["delete"],
                                         undo=out["undo"])
        for old in EditBatch.objects.filter(database=db).order_by("-created_at", "-pk")[editor.KEEP_BATCHES:]:
            old.delete()
        services.logevent("table_edit", f"{t.qualified}: {c['insert']} افزودن، {c['update']} ویرایش، {c['delete']} حذف",
                          user=request.user, database=db)
        resp["batch"] = batch.pk
    elif not out["ok"]:
        resp["error"] = "چند تغییر اعمال نشد؛ هیچ‌چیز ذخیره نشد. خطاها را بررسی کنید."
    return JsonResponse(resp)


@_edit_json
@require_POST
def explore_edit_undo(request, pk, schema, table):
    data = _body(request)
    db, ex, t = _edit_guard(request, pk, schema, table)
    batch = EditBatch.objects.filter(database=db, schema=t.schema, table=t.name, undone_at__isnull=True).first()
    if batch is None or batch.pk != data.get("batch"):
        raise EditError("ذخیره‌ی تازه‌تری وجود دارد یا چیزی برای بازگرداندن نیست؛ صفحه را تازه کنید.")
    out = Editor(ex).apply(t, batch.undo, internal=True)
    if not out["ok"]:
        return JsonResponse({"ok": False, "results": out["results"],
                             "error": "بازگردانی ممکن نشد؛ بعد از آن ذخیره، ردیف‌ها دوباره تغییر کرده‌اند. چیزی برگردانده نشد."},
                            status=409)
    batch.undone_at = timezone.now()
    batch.save(update_fields=["undone_at"])
    services.logevent("table_edit_undo", f"ذخیره‌ی {batch.created_at:%H:%M} برگردانده شد: {t.qualified}",
                      user=request.user, database=db)
    return JsonResponse({"ok": True})


# ---------------------------------------------------------------------- یافتن عارضه
def _find_json(view):
    from .find import FindError

    def wrapper(request, pk):
        try:
            return view(request, pk)
        except FindError as exc:
            return JsonResponse({"ok": False, "error": str(exc), "detail": exc.detail}, status=400)
        except ExplorerError as exc:
            return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    wrapper.__name__ = view.__name__
    return site_user_required(wrapper)


def _finder(request, pk, need: str = "viewer"):
    from .find import Finder, FindError

    db = _user_db(request, pk, need)
    if not db.is_live:
        raise FindError("یافتن عارضه فقط برای پایگاه داده فعال در دسترس است.")
    return db, Finder(Explorer(db))


@site_user_required
def find(request, pk):
    from . import find_credits
    from .find import OPS, RELS, Finder, layer_catalog

    db, ex = _explorer_db(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    try:
        layers = layer_catalog(Finder(ex))
    except ExplorerError as exc:
        messages.error(request, str(exc))
        return redirect("databases:detail", pk=db.pk)
    layers.sort(key=lambda x: (not x["geom"], x["key"]))
    start = request.GET.get("t", "")
    cfg = {
        "layers": layers, "start": start if any(x["key"] == start for x in layers) else "",
        "ops": {k: [[o, t, n] for o, t, n in v] for k, v in OPS.items()}, "rels": RELS,
        "credits": find_credits.status(db),
        "urls": {"cols": reverse("databases:find_columns", args=[db.pk]),
                 "values": reverse("databases:find_values", args=[db.pk]),
                 "run": reverse("databases:find_run", args=[db.pk]),
                 "save": reverse("databases:find_save", args=[db.pk]),
                 "status": reverse("databases:find_save_status", args=[db.pk]),
                 "sql": reverse("databases:find_sql", args=[db.pk]),
                 "addmap": reverse("maps:add_table", args=[db.pk]),
                 "plans": reverse("billing:plans"),
                 "geojson": reverse("databases:explore_geojson", args=[db.pk, "__s__", "__t__"])},
        "csrf": get_token(request),
        "can_edit": bool(db.can_edit and db.status == UserDatabase.Status.ACTIVE),
        "edit_note": "" if db.can_edit else "ذخیره‌ی لایه برای ویرایشگر و مالک پایگاه داده است.",
    }
    return render(request, "databases/find.html", {"db": db, "section": "find", "cfg": cfg,
                                                   "has_layers": bool(layers)})


@_find_json
def find_columns(request, pk):
    from .find import column_catalog

    _db, finder = _finder(request, pk)
    return JsonResponse({"ok": True, "columns": column_catalog(finder, request.GET.get("t", ""))})


@_find_json
def find_values(request, pk):
    _db, finder = _finder(request, pk)
    return JsonResponse({"ok": True, **finder.values(request.GET.get("t", ""), request.GET.get("col", ""))})


@_find_json
@require_POST
def find_run(request, pk):
    from . import find_credits
    from .find import FindError, spec_hash, uses_other_layer

    if len(request.body) > 512 * 1024:
        raise FindError("شکل کشیده‌شده بیش از حد بزرگ است.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise FindError("درخواست نامعتبر است.") from exc
    spec = data.get("spec") if isinstance(data, dict) else None
    if not isinstance(spec, dict):
        raise FindError("درخواست نامعتبر است.")
    db, finder = _finder(request, pk)
    cross = uses_other_layer(spec)
    h = spec_hash(spec)
    if not find_credits.check(db, h, cross):
        st = find_credits.status(db)
        msg = ("پلن این پایگاه داده شرط مکانی بین لایه‌ها را ندارد." if not st["cap"] else
               f"اعتبار شرط مکانی بین لایه‌ها ({st['cap']} بار در ۳۰ روز) تمام شده است.")
        return JsonResponse({"ok": False, "error": msg + " شرط توصیفی و شکل کشیده‌شده همچنان آزاد است.",
                             "credits": st, "upgrade": True}, status=402)
    try:
        page = int(data.get("page") or 1)
    except (TypeError, ValueError):
        page = 1
    result = finder.run(spec, page)
    charged = find_credits.record(db, request.user, h, result["layer"], cross)
    return JsonResponse({"ok": True, **result, "charged": charged, "credits": find_credits.status(db)})


def _find_body(request) -> dict:
    from .find import FindError

    if len(request.body) > 1024 * 1024:
        raise FindError("درخواست بیش از حد بزرگ است.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError as exc:
        raise FindError("درخواست نامعتبر است.") from exc
    if not isinstance(data, dict) or not isinstance(data.get("spec"), dict):
        raise FindError("درخواست نامعتبر است.")
    return data


@_find_json
@require_POST
def find_sql(request, pk):
    """دستور SQL معادل ذخیره‌ی این نتیجه (برای یادگیری و استفاده در کنسول SQL)؛ هیچ‌چیز اجرا نمی‌شود."""
    from . import find_save as fs

    data = _find_body(request)
    db, finder = _finder(request, pk)
    opts = data.get("opts") if isinstance(data.get("opts"), dict) else {}
    plan = fs.build(finder, data["spec"], {"name": "find_result", **opts})
    with finder.ex.connect() as conn:
        text = fs.statement_text(conn, plan)
    return JsonResponse({"ok": True, "sql": text, "console": reverse("databases:explore_sql", args=[db.pk])})


@_find_json
@require_POST
def find_save(request, pk):
    """صف کردن ساخت لایه (جدول ثابت یا نمای زنده) از نتیجه‌ی یافتن عارضه؛ همیشه در پس‌زمینه."""
    from jobs.models import Job

    from . import find_credits
    from . import find_save as fs
    from .find import FindError, spec_hash, uses_other_layer

    data = _find_body(request)
    db, finder = _finder(request, pk, "editor")
    if db.status != UserDatabase.Status.ACTIVE:
        raise FindError("پایگاه داده فقط‌خواندنی است (حجم پر یا منقضی)؛ ساخت لایه ممکن نیست.")
    spec = data["spec"]
    plan = fs.build(finder, spec, data.get("opts"))
    fs.check_name(finder.ex, plan)
    if Job.objects.filter(database=db, kind=Job.Kind.FIND,
                          status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists():
        raise FindError("ساخت یک لایه‌ی دیگر در جریان است؛ صبر کنید تمام شود.")
    cross = uses_other_layer(spec)
    h = spec_hash(spec)
    if not find_credits.check(db, h, cross):
        st = find_credits.status(db)
        return JsonResponse({"ok": False, "credits": st, "upgrade": True,
                             "error": "اعتبار شرط مکانی بین لایه‌ها تمام شده است. شرط توصیفی و شکل کشیده‌شده همچنان آزاد است."},
                            status=402)
    find_credits.record(db, request.user, h, plan.source, cross)
    job = Job.objects.create(kind=Job.Kind.FIND, database=db, user=request.user, status=Job.Status.QUEUED,
                             params={"spec": spec, "opts": fs.parse_opts(data.get("opts"))})
    return JsonResponse({"ok": True, "job": job.pk, "credits": find_credits.status(db)})


@_find_json
def find_save_status(request, pk):
    from jobs.models import Job

    db, _finder_ = _finder(request, pk)
    job = Job.objects.filter(pk=request.GET.get("job") or 0, database=db, kind=Job.Kind.FIND).first() \
        if str(request.GET.get("job", "")).isdigit() else None
    if job is None:
        return JsonResponse({"ok": False, "error": "این کار پیدا نشد."}, status=404)
    out = {"ok": True, "status": job.status, "progress": job.progress, "stage": job.stage}
    if job.status == Job.Status.DONE:
        res = job.params.get("result") or {}
        schema, _, name = (res.get("table") or "").partition(".")
        out.update({"message": job.message, "table": res.get("table"), "rows": res.get("rows"), "kind": res.get("kind"),
                    "urls": {"table": reverse("databases:explore_table", args=[db.pk, schema, name]) if name else "",
                             "find": reverse("databases:find", args=[db.pk]) + f"?t={res.get('table')}"}})
    elif job.status == Job.Status.FAILED:
        out["error"] = (job.message or "ساخت لایه ناموفق بود.").splitlines()[0][:300]
    return JsonResponse(out)
