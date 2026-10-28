"""صفحه «تحلیل»: پرسش فارسی (s3geo با کلید خود کاربر) و ابزارهای آماده بدون SQL."""
from urllib.parse import urlencode, urlsplit

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases.explorer import ExplorerError
from databases.views import _explorer_db
from jobs.models import Job

from . import ask, tools
from .models import LlmConfig, Question, ToolRun

HISTORY_LIMIT = 15
# پیشنهاد نمودار برای نتیجه هر ابزار: «ساخت نقشه و نمودار» جدول نتیجه را به نقشه می‌برد و فرم نمودار را پر می‌کند
CHART_HINTS = {
    "nearest": {"kind": "hist", "field": "distance_m", "cumulative": "1"},
    "count": {"kind": "hist", "field": "point_count"},
    "overlap": {"kind": "stacked", "field": "zone", "series": "category", "value": "area_m2", "agg": "sum", "percent": "1"},
    "hexbin": {"kind": "hist", "field": "count"},
    "change": {"kind": "sankey", "field": "from_category", "target": "to_category", "value": "area_m2", "agg": "sum"},
}
# نام فارسی مرحله‌های رایج برنامهٔ s3geo در گزارش مرحله‌به‌مرحلهٔ پرسش
OP_LABELS = {
    "input": "ورودی", "crs_transform": "تبدیل مختصات", "filter_attribute": "فیلتر ستونی", "sort_limit": "مرتب‌سازی",
    "spatial_nearest": "نزدیک‌ترین", "nearest_neighbor": "نزدیک‌ترین", "filter_by_distance": "فیلتر فاصله",
    "spatial_join": "اتصال مکانی", "filter_points_in_polygon": "نقطه در چندضلعی", "buffer": "حریم",
    "summarize_vector": "خلاصه", "attribute_statistics": "آمار ستونی", "top_n": "برترین‌ها", "dissolve": "ادغام",
    "area_perimeter": "طول و مساحت", "calculate_field": "محاسبه ستون", "distance_to": "فاصله",
}
GLYPHS = {"buffer": "◎", "nearest": "⌖", "count": "#", "overlap": "▦", "change": "⇄", "hexbin": "⬡", "isochrone": "◔"}


def _busy(db) -> bool:
    return Job.objects.filter(database=db, kind__in=[Job.Kind.ASK, Job.Kind.TOOL],
                              status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists()


def _together(db, output: str, inputs) -> str:
    """«نمایش با هم»: نتیجه بالای لایه‌های ورودی (بدون ذخیره نقشه)."""
    keys = [f"public.{output}"] + [k for k in (inputs or []) if isinstance(k, str) and k]
    keys = list(dict.fromkeys(keys))
    if len(keys) < 2:
        return ""
    return reverse("maps:quick", args=[db.pk]) + "?" + urlencode([("t", k) for k in keys])


def _entries(db):
    """تاریخچه یکپارچه ابزارها و پرسش‌ها، تازه‌ترین اول."""
    out = []
    for r in ToolRun.objects.filter(database=db).select_related("job")[:HISTORY_LIMIT]:
        t = tools.TOOL_MAP.get(r.tool)
        out.append({"kind": "tool", "id": f"t{r.pk}", "title": t.title if t else r.tool, "glyph": GLYPHS.get(r.tool, "◇"),
                    "detail": r.summary, "table": r.output_table, "rows": r.rows, "job": r.job,
                    "created": r.created_at, "chart": CHART_HINTS.get(r.tool),
                    "together": _together(db, r.output_table, [r.params.get("layer"), r.params.get("other")])})
    for q in Question.objects.filter(database=db).select_related("job")[:HISTORY_LIMIT]:
        steps = [{**s, "label": OP_LABELS.get(s.get("op"), s.get("op"))} for s in q.steps or []]
        out.append({"kind": "ask", "id": f"q{q.pk}", "pk": q.pk, "title": q.text, "glyph": "؟", "detail": q.goal,
                    "ops": q.operations, "steps": steps, "result": q.result_kind, "notes": q.notes,
                    "plan_text": q.plan_text, "summary": q.summary, "preview": q.preview, "followable": q.result_kind == "layer", "answer": q.answer,
                    "table": q.output_table, "rows": q.rows, "job": q.job,
                    "created": q.created_at, "together": _together(db, q.output_table, q.layers)})
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
            cfg.model = (request.POST.get("model") or "gpt-4o").strip()[:100]
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
                            request.POST.get("output", ""), share_values=request.POST.get("share_values") == "on",
                            confirm=request.POST.get("confirm") == "on", parent_pk=request.POST.get("parent"))
            except (ask.AskError, ExplorerError) as exc:
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
        "db": db, "tables": tables, "spatial": spatial, "section": "analysis", "cfg": cfg, "history": history,
        "active": any(e["job"] and e["job"].active for e in history), "tools": tools.TOOLS,
        "open_tool": request.GET.get("tool") if request.GET.get("tool") in tools.TOOL_MAP else tools.TOOLS[0].key, "has_routing": any(t.schema == "routing" and t.name == "ways"
                                                                    for t in tables),
        "max_layers": ask.MAX_LAYERS, "max_auto": ask.MAX_AUTO_LAYERS, "layer_limit": ask.LAYER_LIMIT, "again": again,
        "follow": follow, "prefill_layers": prefill_layers, "parent_pk": parent_pk,
    })
