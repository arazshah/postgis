"""نماهای «یافتن عارضه»."""
import json

from django.contrib import messages
from django.http import JsonResponse
from django.middleware.csrf import get_token
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.decorators import site_user_required
from databases.explorer import Explorer, ExplorerError
from databases.models import UserDatabase
from kernel import workspace


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

    db = workspace.get(request, pk, need)
    if not db.is_live:
        raise FindError("یافتن عارضه فقط برای پایگاه داده فعال در دسترس است.")
    return db, Finder(Explorer(db))


@site_user_required
def find(request, pk):
    from . import find_credits
    from .find import OPS, RELS, Finder, layer_catalog

    db, ex = workspace.open_catalog(request, pk)
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
