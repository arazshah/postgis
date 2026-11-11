"""نمای عمومی صفحه‌های کیت صفحه: `dashboard/<pk>/p/<plugin>/<page>/` (و `?fragment=1` برای تازه‌سازی بدنه)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import entitlements, gate, metering, pagekit, pluginio, tenantdb, workspace


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


@login_required
@require_POST
def submit(request, pk, plugin, page, form):
    """ثبت یک ردیف از فرم صفحه (فقط INSERT؛ سطح ویرایشگر، مجوز پلاگین، سقف ماهانه، ثبت در گزارش فعالیت)."""
    spec = pagekit.get(plugin, page)
    fm = pagekit.get_form(spec, form) if spec else None
    if fm is None:
        raise Http404
    ws = workspace.get(request, pk, spec.need)
    if not entitlements.allowed(plugin, user=request.user, ws=ws):
        raise Http404
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    if not ws.is_live:
        messages.error(request, "این صفحه فقط برای پایگاه داده‌ی فعال در دسترس است.")
        return redirect("databases:detail", pk=ws.pk)
    within, _now, cap = metering.check(plugin, "form_submits", user=request.user, ws=ws)
    if not within:
        messages.error(request, f"سقف ماهانه‌ی ثبت ({cap}) پر شده است؛ برای افزایش با پشتیبانی تماس بگیرید.")
        return back
    values, errors = pagekit.read_form(fm, request.POST)
    if errors:
        for e in errors:
            messages.error(request, e)
        return back
    try:
        pagekit.insert_row(ws, fm, values)
    except pagekit.SpecError as exc:
        messages.error(request, str(exc))
        workspace.log_event("plugin_form", f"{plugin}/{page}/{form}: {exc}", user=request.user, database=ws, success=False)
        return back
    except Exception as exc:  # noqa: BLE001  خطای پایگاه داده (قید، نوع…): متن کوتاه
        msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        messages.error(request, "ثبت انجام نشد: " + ("زمان اجرا تمام شد." if "statement timeout" in msg else "داده با ساختار جدول نمی‌خواند."))
        workspace.log_event("plugin_form", f"{plugin}/{page}/{form}: {msg}", user=request.user, database=ws, success=False)
        return back
    metering.record(plugin, "form_submits", user=request.user, ws=ws)
    workspace.log_event("plugin_form", f"{plugin}/{page}/{form}: یک ردیف در {fm.table} ثبت شد", user=request.user, database=ws)
    messages.success(request, fm.success)
    return back


@csrf_exempt
@gate.public
@require_POST
def runner_sql(request):
    """پل SQL برای سرویس plugin-runner: فقط با توکن کار امضاشده (۶۰ ثانیه، فقط یک پایگاه داده) و فقط SELECT فقط‌خواندنی."""
    import json

    from django.core import signing

    from .runner import remote

    auth = request.headers.get("Authorization", "")
    try:
        ws_pk = remote.read_job_token(auth.removeprefix("Bearer "))
        body = json.loads(request.body[:remote.sandbox.MAX_LINE])
        ws = workspace.peek(ws_pk)
        if ws is None or not getattr(ws, "is_live", False):
            raise ValueError("پایگاه داده در دسترس نیست.")
        return JsonResponse(pagekit.read_select(ws, str(body.get("query", "")), body.get("params")))
    except (signing.BadSignature, KeyError, TypeError):
        return JsonResponse({"error": "forbidden"}, status=403)
    except Exception as exc:  # noqa: BLE001 - پیام کوتاه به کد پلاگین
        return JsonResponse({"error": str(exc).splitlines()[0][:300] if str(exc) else "خطا"}, status=200)


def _io_context(request, pk, plugin, page, kind, key):
    """مشترک ورود/خروج: صفحه و مورد را می‌یابد، دسترسی و مجوز و سقف ماهانه را می‌سنجد. (spec، item، ws) یا پاسخ برای بازگشت."""
    spec = pagekit.get(plugin, page)
    item = (pagekit.get_import if kind == "import" else pagekit.get_export)(spec, key) if spec else None
    if item is None:
        raise Http404
    ws = workspace.get(request, pk, spec.need)
    if not entitlements.allowed(plugin, user=request.user, ws=ws):
        raise Http404
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    if not ws.is_live:
        messages.error(request, "این صفحه فقط برای پایگاه داده‌ی فعال در دسترس است.")
        return None, None, None, redirect("databases:detail", pk=ws.pk)
    within, _now, cap = metering.check(plugin, "io_runs", user=request.user, ws=ws)
    if not within:
        messages.error(request, f"سقف ماهانه‌ی ورود و خروج ({cap}) پر شده است؛ برای افزایش با پشتیبانی تماس بگیرید.")
        return None, None, None, back
    return spec, item, ws, None


@login_required
@require_POST
def import_file(request, pk, plugin, page, key):
    """ورود فایل با handler سطح ۲: handler تبدیل می‌کند؛ هسته جدول **تازه** می‌سازد (docs/adr/0005)."""
    from .runner import client

    spec, item, ws, early = _io_context(request, pk, plugin, page, "import", key)
    if early is not None:
        return early
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    up = request.FILES.get("file")
    if up is None or not up.size:
        messages.error(request, "فایلی انتخاب نشده یا خالی است.")
        return back
    if up.size > client.sandbox.MAX_FILE:
        messages.error(request, "حجم فایل بیش از ۳ مگابایت است.")
        return back
    name = (up.name or "").lower()
    if item.extensions and not name.endswith(tuple(item.extensions)):
        messages.error(request, "پسوند فایل مجاز نیست (مجاز: " + "، ".join(item.extensions) + ").")
        return back
    try:
        table = pluginio.table_name(request.POST.get("table", ""))
    except pluginio.PluginIOError as exc:
        messages.error(request, str(exc))
        return back
    data = up.read(client.sandbox.MAX_FILE + 1)
    try:
        out = client.execute(plugin, item.handler, {"filename": pluginio.safe_filename(up.name, "txt"), "size": len(data)},
                             lambda q, a: pagekit.read_select(ws, q, a), ws.pk, file=data, io=True)
        created = pluginio.create_table(ws, pluginio.normalize_import(table, out))
    except (client.RunnerError, pluginio.PluginIOError) as exc:
        messages.error(request, str(exc))
        workspace.log_event("plugin_import", f"{plugin}/{page}/{key}: {str(exc)[:200]}", user=request.user, database=ws, success=False)
        return back
    except Exception as exc:  # noqa: BLE001 - خطای پایگاه داده (سهمیه، نوع، دسترسی)
        msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
        messages.error(request, "ساخت جدول انجام نشد: " + ("زمان اجرا تمام شد." if "statement timeout" in msg else "پایگاه داده نپذیرفت (سهمیه یا ساختار)."))
        workspace.log_event("plugin_import", f"{plugin}/{page}/{key}: {msg}", user=request.user, database=ws, success=False)
        return back
    metering.record(plugin, "io_runs", user=request.user, ws=ws)
    workspace.log_event("plugin_import", f"{plugin}/{page}/{key}: جدول «{table}» با {created:,} ردیف ساخته شد", user=request.user, database=ws)
    messages.success(request, f"{item.success} ({created:,} ردیف در «{table}»)")
    return back


@login_required
@require_POST
def export_file(request, pk, plugin, page, key):
    """خروجی اختصاصی با handler سطح ۲: فقط attachment با Content-Type فهرست سفید و nosniff."""
    from .runner import client

    spec, item, ws, early = _io_context(request, pk, plugin, page, "export", key)
    if early is not None:
        return early
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    try:
        out = client.execute(plugin, item.handler, {}, lambda q, a: pagekit.read_select(ws, q, a), ws.pk, io=True)
        filename, body, ctype = pluginio.normalize_export(out, item.format)
    except (client.RunnerError, pluginio.PluginIOError) as exc:
        messages.error(request, str(exc))
        workspace.log_event("plugin_export", f"{plugin}/{page}/{key}: {str(exc)[:200]}", user=request.user, database=ws, success=False)
        return back
    metering.record(plugin, "io_runs", user=request.user, ws=ws)
    workspace.log_event("plugin_export", f"{plugin}/{page}/{key}: {filename} ({len(body):,} بایت)", user=request.user, database=ws)
    resp = HttpResponse(body, content_type=f"{ctype}; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    resp["X-Content-Type-Options"] = "nosniff"
    resp["Cache-Control"] = "no-store"
    return resp
