
from django.conf import settings
from django.contrib import messages
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required
from kernel import home
from kernel.workspace import SESSION_PW_KEY

from . import services
from .crypto import generate_password
from .forms import AddExtensionForm, CreateDatabaseForm, DeleteConfirmForm, PasswordResetForm
from .models import UserDatabase
from .provisioner import ProvisionError


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
    can_create, reason = services.user_can_create(request.user)
    return render(request, "databases/dashboard.html", {
        "dbs": dbs, "shared": shared, "can_create": can_create, "stats": stats, "reason": reason,
        **home.collect_context(request, dbs), **_home(request.user, dbs, stats)})


def _greeting(now=None) -> str:
    h = timezone.localtime(now).hour
    return "صبح بخیر" if 5 <= h < 12 else "ظهر بخیر" if 12 <= h < 16 else "عصر بخیر" if 16 <= h < 20 else "شب بخیر"


def _home(user, dbs, stats) -> dict:
    """داده‌ی «خانه»: خوشامد، شمار پایگاه‌های نیازمند توجه، ادامه‌ی کار و چک‌لیست شروع.
    ردیف‌های ادامه‌ی کار و گام‌ها را پلاگین‌ها می‌آورند (kernel.home)؛ چند پرس‌وجوی تجمیعی، نه یکی برای هر پایگاه."""
    live = [d for d in dbs if d.is_live]
    attn_count = sum(1 for d in dbs if d.attn)
    steps = home.collect_steps(user, dbs, live[0] if live else None)
    done = sum(1 for s in steps if s["done"])
    quota = stats["quota"]
    return {"hello": _greeting(), "attn_count": attn_count, "feed": home.collect_feed(user, dbs), "steps": steps,
            "steps_done": done, "steps_pct": round(done * 100 / len(steps)) if steps else 100,
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
