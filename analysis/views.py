"""صفحه «تحلیل»: پرسش فارسی (s3geo با کلید خود کاربر) و ابزارهای آماده بدون SQL."""
from urllib.parse import urlsplit

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases.explorer import ExplorerError
from databases.views import _explorer_db

from . import ask, tools
from .models import LlmConfig, Question


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
            try:
                res = tools.run(db, request.POST.get("tool", ""), request.POST.dict())
            except tools.ToolError as exc:
                messages.error(request, str(exc))
                return redirect(f"{request.path}?tool={request.POST.get('tool', '')}#tools")
            messages.success(request, f"جدول {res['table']} با {res['rows']:,} عارضه ساخته شد.")
            return redirect("databases:explore_table", pk=db.pk, schema="public", table=res["table"])
        return here
    try:
        tables = ex.tables()
    except ExplorerError as exc:
        messages.error(request, str(exc))
        tables = []
    spatial = [t for t in tables if t.geometry]
    questions = Question.objects.filter(database=db).select_related("job")[:10]
    return render(request, "analysis/page.html", {
        "db": db, "tables": tables, "spatial": spatial, "section": "analysis", "cfg": cfg, "questions": questions,
        "active": any(q.job and q.job.active for q in questions), "tools": tools.TOOLS,
        "open_tool": request.GET.get("tool", ""), "has_routing": any(t.schema == "routing" and t.name == "ways"
                                                                    for t in tables),
        "max_layers": ask.MAX_LAYERS,
    })
