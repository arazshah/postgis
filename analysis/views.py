"""صفحه «تحلیل»: پرسش فارسی (s3geo با کلید خود کاربر). ابزارهای آماده بدون SQL در اپ tools هستند."""

from django.contrib import messages
from django.http import Http404, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from jobs.models import Job
from kernel import workspace
from kernel.tenantdb import TenantError

from . import ask, history
from .models import LlmConfig, Question


def _busy(db) -> bool:
    return Job.objects.filter(database=db, kind__in=[Job.Kind.ASK, Job.Kind.TOOL],
                              status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists()


def _entries(db, kinds=("tool", "ask")):
    return history.entries(db, kinds)


@site_user_required
def status(request, pk):
    """وضعیت کارهای در جریان برای نوار پیشرفت (هر چند ثانیه از صفحه پرسیده می‌شود)."""
    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        return JsonResponse({"error": "unavailable"}, status=404)
    now = timezone.now()
    items = []
    for e in _entries(db):
        j = e["job"]
        if j is None:
            continue
        started = j.started_at or j.created_at
        items.append({"id": e["id"], "status": j.status, "progress": j.progress, "stage": j.stage,
                      "elapsed": int(((j.finished_at or now) - started).total_seconds()), "message": j.message})
    return JsonResponse({"items": items, "active": any(i["status"] in ("queued", "running") for i in items)})


@site_user_required
def history_fragment(request, pk):
    """فقط بخش تاریخچه (کارت‌ها و مودال‌ها) برای تازه‌سازی بدون بارگذاری کل صفحه."""
    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        raise Http404
    kind = request.GET.get("k", "ask")
    kinds = ("tool",) if kind == "tool" else ("ask",) if kind == "ask" else ("tool", "ask")
    hist = _entries(db, kinds)
    tool = request.GET.get("tool", "")
    if tool:
        hist = [e for e in hist if e.get("tool") == tool]
    return render(request, "analysis/_history.html", {
        "db": db, "history": hist, "active": any(e["job"] and e["job"].active for e in hist),
        "hist_kinds": kind, "hist_tool": tool, "fragment": True})


@site_user_required
@require_http_methods(["GET", "POST"])
def page(request, pk):
    # لینک‌های قدیمی «?tool=» به بخش مستقل ابزارها می‌روند
    if request.method == "GET" and request.GET.get("tool"):
        from tools.catalog import info

        tool_info = info()

        key = request.GET["tool"]
        return redirect("tools:detail", pk=pk, key=key) if key in tool_info else redirect("tools:page", pk=pk)
    db, ex = workspace.open_catalog(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    cfg = LlmConfig.objects.filter(user=request.user).first()
    if request.method == "POST":
        action = request.POST.get("action", "")
        here = redirect("analysis:page", pk=db.pk)
        if action == "ask":
            if _busy(db):
                messages.error(request, "یک تحلیل در حال اجراست؛ صبر کنید تمام شود.")
                return here
            try:
                ask.request(db, request.user, request.POST.get("question", ""), request.POST.getlist("layers"),
                            request.POST.get("output", ""), share_values=request.POST.get("share_values") == "on",
                            confirm=request.POST.get("confirm") == "on", parent_pk=request.POST.get("parent"))
            except (ask.AskError, TenantError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "پرسش در صف قرار گرفت؛ معمولاً کمتر از یک دقیقه طول می‌کشد.")
            return here
        if action in ("ask_run", "ask_cancel"):
            pk_q = request.POST.get("q", "")
            q = Question.objects.filter(database=db, pk=int(pk_q), result_kind=Question.Result.PLAN).first() \
                if pk_q.isdigit() else None
            if q is None:
                messages.error(request, "این برنامه دیگر در انتظار تأیید نیست.")
            elif action == "ask_cancel":
                q.delete()
                messages.success(request, "پرسش لغو شد.")
            elif _busy(db):
                messages.error(request, "یک تحلیل در حال اجراست؛ صبر کنید تمام شود.")
            else:
                q.job = Job.objects.create(kind=Job.Kind.ASK, database=db, user=request.user, status=Job.Status.QUEUED)
                q.result_kind = ""
                q.save(update_fields=["job", "result_kind"])
                messages.success(request, "برنامه تأیید شد و در صف اجرا قرار گرفت.")
            return redirect(f"{request.path}#history")
        return here
    try:
        tables = ex.tables()
    except TenantError as exc:
        messages.error(request, str(exc))
        tables = []
    spatial = [t for t in tables if t.geometry]
    hist = _entries(db, ("ask",))
    # «ویرایش و پرسش دوباره»: فرم پرسش با متن، لایه‌ها و نام جدول یک پرسش قبلی پر می‌شود
    again = follow = None
    if request.GET.get("again", "").isdigit():
        again = Question.objects.filter(database=db, pk=int(request.GET["again"])).first()
    if request.GET.get("follow", "").isdigit():
        follow = Question.objects.filter(database=db, pk=int(request.GET["follow"]),
                                         result_kind=Question.Result.LAYER).first()
    # لایه‌های از پیش‌انتخاب‌شده: برای «ادامه» خروجی پرسش قبلی (که جدول مکانی خود پایگاه است) و ورودی‌های آن
    prefill_layers = list(dict.fromkeys(
        ([f"public.{follow.output_table}"] + list(follow.layers)) if follow else (again.layers if again else [])))[:ask.MAX_LAYERS]
    parent_pk = follow.pk if follow else (again.parent_id if again else None)
    return render(request, "analysis/page.html", {
        "db": db, "tables": tables, "spatial": spatial, "section": "analysis", "cfg": cfg, "history": hist,
        "active": any(e["job"] and e["job"].active for e in hist), "hist_kinds": "ask",
        "max_layers": ask.MAX_LAYERS, "max_auto": ask.MAX_AUTO_LAYERS, "layer_limit": ask.LAYER_LIMIT, "again": again,
        "follow": follow, "prefill_layers": prefill_layers, "parent_pk": parent_pk,
    })
