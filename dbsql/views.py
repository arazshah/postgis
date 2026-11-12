"""نماهای «اجرای SQL» و پرسش فارسی."""

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from accounts.decorators import site_user_required
from databases.explorer import SQL_MAX_ROWS, ExplorerError
from kernel import workspace


@site_user_required
@require_http_methods(["GET", "POST"])
def explore_sql(request, pk):
    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return redirect("databases:detail", pk=db.pk)
    from databases import nl2sql

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
    from databases import nl2sql

    db, ex = workspace.open_catalog(request, pk)
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
    from databases import nl2sql

    db, ex = workspace.open_catalog(request, pk)
    if ex is None:
        return JsonResponse({"ok": False, "error": "مرورگر فقط برای پایگاه داده فعال در دسترس است."}, status=400)
    try:
        data = nl2sql.diagnose_empty(db, request.user, request.POST.get("query", ""), request.POST.get("text", ""))
    except nl2sql.NLError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    return JsonResponse({"ok": True, **data})
