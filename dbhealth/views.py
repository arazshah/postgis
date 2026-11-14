"""نمای «سلامت داده»."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from databases.explorer import Explorer, ExplorerError
from databases.models import UserDatabase
from kernel import tables as plugin_tables
from kernel import workspace

# ---------------------------------------------------------------------- ورود فایل
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


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
    from databases.gdal import SRID_CHOICES

    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    if request.method == "POST":
        if not db.can_edit:
            messages.error(request, "برای اصلاح داده باید ویرایشگر یا مالک باشید.")
        elif db.status != UserDatabase.Status.ACTIVE:
            messages.error(request, "پایگاه داده فقط‌خواندنی یا غیرفعال است؛ اصلاح ممکن نیست.")
        else:
            try:
                if request.POST.get("fix") == "plugin_tables":
                    try:
                        done = plugin_tables.rebuild(db, request.POST.get("plugin") or None)
                    except plugin_tables.TableError as exc:
                        messages.error(request, str(exc))
                    else:
                        messages.success(request, ("جدول‌های بازسازی‌شده (خالی): " + "، ".join(done)) if done else "همه‌ی جدول‌های پلاگین‌ها سالم است.")
                    return redirect("databases:explore_health", pk=db.pk)
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
        "plugin_tables": [r for r in plugin_tables.status(db) if r["state"] in ("missing", "columns")],
        "srid_common": SRID_CHOICES[:1] + [c for c in SRID_CHOICES if c[0] in (32639, 3857)],
        "srid_other": [c for c in SRID_CHOICES if c[0] not in (4326, 32639, 3857)],
        **_health_context(tables, issues)})
