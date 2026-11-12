"""نمای «مصرف و کارایی»."""

from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from accounts.decorators import site_user_required
from kernel import charts, events, workspace


# ---------------------------------------------------------------------- داشبورد مصرف
@site_user_required
@require_http_methods(["GET", "POST"])
def usage_page(request, pk):
    from . import usage

    db = workspace.get(request, pk, "editor")
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
    return render(request, "databases/usage.html", {
        "db": db, "stats": stats, "error": error, "history": hist,
        "size_chart": charts.bars([h["size"] for h in hist], [h["day"] for h in hist], db.quota_bytes),
        "usage_cards": [c for c in events.collect(events.USAGE_CARDS, ws=db, request=request) if isinstance(c, dict)],
    })
