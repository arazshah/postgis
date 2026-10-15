"""صفحه «تحلیل»: پرسش فارسی (s3geo با کلید خود کاربر) و ابزارهای آماده بدون SQL."""
from urllib.parse import urlsplit

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases.explorer import ExplorerError
from databases.views import _explorer_db

from . import ask, tools
from jobs.models import Job

from .models import LlmConfig, Question, ToolRun

HISTORY_LIMIT = 15
GLYPHS = {"buffer": "◎", "nearest": "⌖", "count": "#", "hexbin": "⬡", "isochrone": "◔"}


def _busy(db) -> bool:
    return Job.objects.filter(database=db, kind__in=[Job.Kind.ASK, Job.Kind.TOOL],
                              status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists()


def _entries(db):
    """تاریخچه یکپارچه ابزارها و پرسش‌ها، تازه‌ترین اول."""
    out = []
    for r in ToolRun.objects.filter(database=db).select_related("job")[:HISTORY_LIMIT]:
        t = tools.TOOL_MAP.get(r.tool)
        out.append({"kind": "tool", "id": f"t{r.pk}", "title": t.title if t else r.tool, "glyph": GLYPHS.get(r.tool, "◇"),
                    "detail": r.summary, "table": r.output_table, "rows": r.rows, "job": r.job,
                    "created": r.created_at})
    for q in Question.objects.filter(database=db).select_related("job")[:HISTORY_LIMIT]:
        out.append({"kind": "ask", "id": f"q{q.pk}", "title": q.text, "glyph": "؟", "detail": q.goal,
                    "ops": q.operations, "table": q.output_table, "rows": q.rows, "job": q.job,
                    "created": q.created_at})
    out.sort(key=lambda e: e["created"], reverse=True)
    return out[:HISTORY_LIMIT]


@site_user_required
def status(request, pk):
    """وضعیت کارهای در جریان برای نوار پیشرفت (هر چند ثانیه از صفحه پرسیده می‌شود)."""
    db, ex = _explorer_db(request, pk, "editor")
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
@require_http_methods(["GET", "POST"])
def page(request, pk):
    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    cfg = LlmConfig.objects.filter(user=request.user).first()
    if request.method == "POST":
        action = request.POST.get("action", "")
        here = redirect("analysis:page", pk=db.pk)
        if action == "llm_save":
            url = (request.POST.get("base_url") or "").strip().rstrip("/")
            key = (request.POST.get("api_key") or "").strip()
            parts = urlsplit(url)
            if parts.scheme != "https" or not parts.netloc:
                messages.error(request, "آدرس سرویس باید با https شروع شود؛ مثلاً https://api.avalai.ir/v1")
                return here
            if not key and cfg is None:
                messages.error(request, "کلید API را وارد کنید.")
                return here
            cfg = cfg or LlmConfig(user=request.user)
            cfg.base_url = url
            cfg.model = (request.POST.get("model") or "gpt-4o-mini").strip()[:100]
            if key:
                cfg.set_key(key)
            cfg.save()
            messages.success(request, "تنظیم مدل زبانی ذخیره شد.")
            return here
        if action == "llm_delete" and cfg:
            cfg.delete()
            messages.success(request, "کلید مدل زبانی حذف شد.")
            return here
        if action == "ask":
            if _busy(db):
                messages.error(request, "یک تحلیل در حال اجراست؛ صبر کنید تمام شود.")
                return here
            try:
                ask.request(db, request.user, request.POST.get("question", ""), request.POST.getlist("layers"),
                            request.POST.get("output", ""))
            except (ask.AskError, ExplorerError) as exc:
                messages.error(request, str(exc))
            else:
                messages.success(request, "پرسش در صف قرار گرفت؛ معمولاً کمتر از یک دقیقه طول می‌کشد.")
            return here
        if action == "tool":
            if db.status != db.Status.ACTIVE:
                messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است.")
                return here
            key = request.POST.get("tool", "")
            params = {k: request.POST.get(k, "").strip() for k in tools.PUBLIC_PARAMS if request.POST.get(k)}
            if _busy(db):
                messages.error(request, "یک تحلیل در حال اجراست؛ صبر کنید تمام شود.")
                return redirect(f"{request.path}?tool={key}#tools")
            try:
                out = tools.validate(db, key, params)
                summary = tools.summarize(db, key, params)
            except (tools.ToolError, ExplorerError) as exc:
                messages.error(request, str(exc))
                return redirect(f"{request.path}?tool={key}#tools")
            job = Job.objects.create(kind=Job.Kind.TOOL, database=db, user=request.user, status=Job.Status.QUEUED)
            ToolRun.objects.create(database=db, user=request.user, tool=key, params=params, summary=summary,
                                   output_table=out, job=job)
            return redirect(f"{request.path}#history")
        return here
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    spatial = [t for t in tables if t.geometry]
    history = _entries(db)
    return render(request, "analysis/page.html", {
        "db": db, "tables": tables, "spatial": spatial, "section": "analysis", "cfg": cfg, "history": history,
        "active": any(e["job"] and e["job"].active for e in history), "tools": tools.TOOLS,
        "open_tool": request.GET.get("tool") if request.GET.get("tool") in tools.TOOL_MAP else tools.TOOLS[0].key, "has_routing": any(t.schema == "routing" and t.name == "ways"
                                                                    for t in tables),
        "max_layers": ask.MAX_LAYERS,
    })
