"""بخش «ابزارها»: گالری ابزارهای آماده بدون SQL، فرم هر ابزار (ساخته‌شده از کاتالوگ) و تاریخچهٔ اجرا."""
from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from analysis import history
from analysis.models import ToolRun
from databases.views import _explorer_db
from jobs.models import Job
from kernel.tenantdb import TenantError

from . import engine, sdk
from .catalog import category_groups


def _geom_ok(t, want: str) -> bool:
    if not want:
        return True
    kinds = {(g.get("type") or "").upper() for g in t.geometry}
    if not kinds or kinds & {"GEOMETRY", ""}:
        return True
    return any(want.upper() in k for k in kinds)


def _layers(spatial, want: str):
    return [{"value": f"{t.schema}.{t.name}", "label": t.name,
             "type": ((t.geometry[0].get("type") or "") if t.geometry else "").lower()}
            for t in spatial if _geom_ok(t, want)]


def _has_routing(tables) -> bool:
    return any(t.schema == "routing" and t.name == "ways" for t in tables)


def _blocked(info, spatial, has_routing) -> str:
    """دلیل غیرفعال بودن ابزار برای این پایگاه (خالی = آماده)."""
    if info.needs_routing and not has_routing:
        return "به شبکه معابر نیاز دارد"
    for p in info.params:
        if p.kind == "layer" and p.required and not _layers(spatial, p.geom):
            what = {"point": "نقطه‌ای", "polygon": "چندضلعی", "line": "خطی"}.get(p.geom, "مکانی")
            return f"لایه {what} ندارید"
    return ""


def _busy(db) -> bool:
    return Job.objects.filter(database=db, kind__in=[Job.Kind.ASK, Job.Kind.TOOL],
                              status__in=[Job.Status.QUEUED, Job.Status.RUNNING]).exists()


def _context(request, pk):
    db, ex = _explorer_db(request, pk, "editor")
    if ex is None:
        return db, None, [], []
    try:
        tables = ex.tables()
    except TenantError as exc:
        messages.error(request, str(exc))
        tables = []
    return db, ex, tables, [t for t in tables if t.geometry]


@site_user_required
def index(request, pk):
    db, ex, tables, spatial = _context(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    routing = _has_routing(tables)
    groups = category_groups()
    for g in groups:
        g["cards"] = [{"info": i, "blocked": _blocked(i, spatial, routing),
                       "url": reverse("tools:detail", args=[db.pk, i.key])} for i in g["tools"]]
    hist = history.entries(db, ("tool",), 8)
    return render(request, "tools/index.html", {
        "db": db, "section": "tools", "groups": groups, "total": len(sdk.all_tools()), "history": hist,
        "active": any(e["job"] and e["job"].active for e in hist), "hist_kinds": "tool"})


@site_user_required
@require_http_methods(["GET", "POST"])
def detail(request, pk, key):
    info = sdk.get(key)
    if info is None:
        raise Http404
    db, ex, tables, spatial = _context(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    routing = _has_routing(tables)
    blocked = _blocked(info, spatial, routing)
    vals = {}
    if request.method == "POST":
        vals = {k: request.POST.get(k, "").strip() for k in engine.public_params(key) if request.POST.get(k)}
        if db.status != db.Status.ACTIVE:
            messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است.")
        elif blocked:
            messages.error(request, f"این ابزار برای این پایگاه آماده نیست: {blocked}.")
        elif _busy(db):
            messages.error(request, "یک تحلیل در حال اجراست؛ صبر کنید تمام شود.")
        else:
            try:
                out = engine.validate(db, key, vals)
                summary = engine.summarize(db, key, vals)
            except (engine.ToolError, TenantError) as exc:
                messages.error(request, str(exc))
            else:
                job = Job.objects.create(kind=Job.Kind.TOOL, database=db, user=request.user, status=Job.Status.QUEUED)
                ToolRun.objects.create(database=db, user=request.user, tool=key, params=vals, summary=summary,
                                       output_table=out, job=job)
                messages.success(request, "تحلیل در صف قرار گرفت؛ پایان آن اعلام می‌شود.")
                return redirect(reverse("tools:detail", args=[db.pk, key]) + "#history")
    fields = []
    for p in (*info.params, ):
        v = vals.get(p.name, p.default)
        f = {"p": p, "value": v, "id": f"f-{p.name}"}
        if p.kind == "layer":
            f["options"] = _layers(spatial, p.geom)
        elif p.kind == "bool":
            f["checked"] = vals.get(p.name) == "on" if request.method == "POST" else False
        fields.append(f)
    hist = [e for e in history.entries(db, ("tool",), 40) if e["tool"] == key][:8]
    return render(request, "tools/detail.html", {
        "db": db, "section": "tools", "info": info, "fields": fields, "blocked": blocked,
        "out_value": vals.get("output", f"{key}_result"), "replace": vals.get("replace") == "on",
        "history": hist, "active": any(e["job"] and e["job"].active for e in hist) or _busy(db),
        "hist_kinds": "tool", "hist_tool": key})
