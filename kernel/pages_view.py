"""نمای عمومی صفحه‌های کیت صفحه: `dashboard/<pk>/p/<plugin>/<page>/` (و `?fragment=1` برای تازه‌سازی بدنه)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET

from . import entitlements, metering, pagekit, tenantdb, workspace


@login_required
@require_GET
def page(request, pk, plugin, page):
    spec = pagekit.get(plugin, page)
    if spec is None:
        raise Http404
    ws = workspace.get(request, pk, spec.need)  # سطح دسترسی صفحه؛ نبودن = ۴۰۴
    if not entitlements.allowed(plugin, user=request.user, ws=ws):
        raise Http404
    within, now, cap = metering.check(plugin, "page_views", user=request.user, ws=ws)
    if not within:
        messages.error(request, f"سقف ماهانه‌ی بازدید این صفحه ({cap}) پر شده است؛ برای افزایش با پشتیبانی تماس بگیرید.")
        return redirect("databases:detail", pk=ws.pk)
    if not ws.is_live:
        messages.error(request, "این صفحه فقط برای پایگاه داده‌ی فعال در دسترس است.")
        return redirect("databases:detail", pk=ws.pk)
    layers: dict[str, str] = {}
    if any(p.kind == "layer" for p in spec.params):
        try:
            layers = {f"{t.schema}.{t.name}": t.name for t in tenantdb.catalog(ws).tables()}
        except tenantdb.TenantError as exc:
            messages.error(request, str(exc))
    if request.GET.get("fragment") != "1":  # تازه‌سازی خودکار بازدید جدید نیست
        metering.record(plugin, "page_views", user=request.user, ws=ws)
    values, errors = pagekit.read_values(spec, request.GET, layers)
    blocks = [pagekit.render_block(ws, spec, b, values) for b in spec.blocks]
    ctx = {"db": ws, "page": spec, "blocks": blocks, "values": values, "layers": layers, "param_errors": errors,
           "has_map": any(b["kind"] == "map" for b in blocks), "section": "pages"}
    template = "kernel/_page_body.html" if request.GET.get("fragment") == "1" else "kernel/page.html"
    return render(request, template, ctx)
