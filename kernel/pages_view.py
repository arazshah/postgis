"""نمای عمومی صفحه‌های کیت صفحه: `dashboard/<pk>/p/<plugin>/<page>/` (و `?fragment=1` برای تازه‌سازی بدنه)."""
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.clickjacking import xframe_options_sameorigin
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

from . import (
    caps,
    entitlements,
    gate,
    ingest,
    metering,
    pagekit,
    platform,
    pluginio,
    reports,
    sources,
    tables,
    tenantdb,
    workspace,
)


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
    if spec.tables:
        try:
            tables.ensure(ws, plugin, spec.tables)  # جدول‌های اعلام‌شده‌ی پلاگین (نخستین استفاده در این پایگاه)
        except tables.TableError as exc:
            messages.error(request, str(exc))
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
    ingests = []
    if spec.ingests:
        new = request.session.pop("ingest_new", None)
        for i in spec.ingests:
            ingests.append({"spec": i, "tokens": ingest.tokens_for(ws, plugin, page, i.key),
                            "new": new if new and new.get("key") == i.key and new.get("ws") == ws.pk else None})
    cap = {c: caps.allowed(c, user=request.user, ws=ws) for c in ("sources", "draw", "reports")}
    forms = [f for f in spec.forms if cap["draw"] or not any(fd.kind == "geometry" for fd in f.fields)]
    srcs = []
    if spec.sources and cap["sources"]:
        from .models import SourceState

        states = {x.key: x for x in SourceState.objects.filter(plugin_id=plugin, page=page, workspace_id=ws.pk)}
        for x in spec.sources:
            st = states.get(x.key)
            vals = (st.inputs if st else {}) or {}
            srcs.append({"spec": x, "state": st, "host_ok": sources.host_allowed(x.host),
                         "inputs": [{"i": i, "value": vals.get(i.name, i.default)} for i in x.inputs]})
    recs = []
    for rc in (spec.records if cap["draw"] else ()):
        try:
            heads, rows = pagekit.fetch_records(ws, rc)
            recs.append({"spec": rc, "heads": heads[1:], "rows": rows, "error": ""})
        except pagekit.SpecError as exc:
            recs.append({"spec": rc, "heads": [], "rows": [], "error": str(exc)})
        except Exception:  # noqa: BLE001  جدول هنوز ساخته نشده یا خطای پایگاه داده: پیام کوتاه
            recs.append({"spec": rc, "heads": [], "rows": [], "error": "خواندن ردیف‌ها ممکن نشد."})
    ctx = {"db": ws, "page": spec, "blocks": blocks, "ingests": ingests, "sources": srcs, "records": recs, "sources_on": platform.sources_enabled(), "can_manage_ingest": workspace.level(request.user, ws) >= 2,
           "ingest_url": request.build_absolute_uri("/ingest/"), "values": values, "layers": layers, "param_errors": errors,
           "has_map": any(b["kind"] == "map" for b in blocks),
           "has_draw": any(fd.kind == "geometry" for fm in forms for fd in fm.fields), "forms": forms, "cap_reports": cap["reports"],
           "can_edit_rows": workspace.level(request.user, ws) >= 1 and spec.need != "viewer", "section": "pages"}
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
    if any(fd.kind == "geometry" for fd in fm.fields) and not caps.allowed("draw", user=request.user, ws=ws):
        raise Http404  # فرم دارای فیلد هندسه به پلاگین «ترسیم روی نقشه» وابسته است
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    if not ws.is_live:
        messages.error(request, "این صفحه فقط برای پایگاه داده‌ی فعال در دسترس است.")
        return redirect("databases:detail", pk=ws.pk)
    within, _now, cap = metering.check(plugin, "form_submits", user=request.user, ws=ws)
    if not within:
        messages.error(request, f"سقف ماهانه‌ی ثبت ({cap}) پر شده است؛ برای افزایش با پشتیبانی تماس بگیرید.")
        return back
    if spec.tables:
        try:
            tables.ensure(ws, plugin, spec.tables)
        except tables.TableError as exc:
            messages.error(request, str(exc))
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


# ---------------------------------------------------------------------- دریافت داده‌ی دستگاه (docs/plugins/ingest.md)
@csrf_exempt
@gate.public
@require_POST
def ingest_receive(request):
    """نشانی عمومی دریافت: احراز هویت فقط با توکن (Authorization: Bearer)؛ پاسخ JSON کوتاه بدون جزئیات داخلی."""
    try:
        out = ingest.receive(request)
    except ingest.IngestError as exc:
        resp = JsonResponse({"ok": False, "error": exc.message}, status=exc.status)
    else:
        resp = JsonResponse({"ok": True, **out})
    resp["Cache-Control"] = "no-store"
    return resp


def _ingest_target(request, pk, plugin, page, key):
    spec = pagekit.get(plugin, page)
    item = pagekit.get_ingest(spec, key) if spec else None
    if item is None:
        raise Http404
    ws = workspace.get(request, pk, "owner")  # توکن مثل رمز است: فقط مالک می‌سازد و باطل می‌کند
    if not entitlements.allowed(plugin, user=request.user, ws=ws):
        raise Http404
    return ws, redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)


@login_required
@require_POST
def ingest_token_create(request, pk, plugin, page, key):
    ws, back = _ingest_target(request, pk, plugin, page, key)
    try:
        row, raw = ingest.create_token(ws, plugin, page, key, request.user, request.POST.get("label", ""))
    except ingest.IngestError as exc:
        messages.error(request, exc.message)
        return back
    request.session["ingest_new"] = {"ws": ws.pk, "key": key, "token": raw, "id": row.pk}  # یک‌بار نمایش
    workspace.log_event("plugin_ingest_token", f"{plugin}/{page}/{key}: توکن {row.prefix}… ساخته شد", user=request.user, database=ws)
    return back


@login_required
@require_POST
def ingest_token_revoke(request, pk, plugin, page, key, token_id):
    ws, back = _ingest_target(request, pk, plugin, page, key)
    if ingest.revoke_token(ws, token_id):
        workspace.log_event("plugin_ingest_token", f"{plugin}/{page}/{key}: توکن {token_id} باطل شد", user=request.user, database=ws)
        messages.success(request, "توکن باطل شد.")
    else:
        messages.error(request, "توکن پیدا نشد.")
    return back


def _source_target(request, pk, plugin, page, key):
    spec = pagekit.get(plugin, page)
    item = pagekit.get_source(spec, key) if spec else None
    if item is None:
        raise Http404
    ws = workspace.get(request, pk, "owner")  # کلید API مثل رمز است: فقط مالک
    if not entitlements.allowed(plugin, user=request.user, ws=ws) or not caps.allowed("sources", user=request.user, ws=ws):
        raise Http404
    return ws, spec, item, redirect(f"{reverse('kernel:page', kwargs={'pk': ws.pk, 'plugin': plugin, 'page': page})}#source-{key}")


@login_required
@require_POST
def source_save(request, pk, plugin, page, key):
    """ذخیره‌ی ورودی‌ها/کلید و فعال‌سازی یا خاموش‌کردن منبع."""
    ws, spec, item, back = _source_target(request, pk, plugin, page, key)
    if request.POST.get("do") == "disable":
        sources.disable(ws, plugin, page, key)
        workspace.log_event("plugin_source", f"{plugin}/{page}/{key}: خاموش شد", user=request.user, database=ws)
        messages.success(request, "دریافت خودکار خاموش شد.")
        return back
    try:
        sources.configure(ws, plugin, spec, item, request.POST, enable=request.POST.get("do") == "enable")
    except ValueError as exc:
        messages.error(request, str(exc))
        return back
    workspace.log_event("plugin_source", f"{plugin}/{page}/{key}: تنظیم ذخیره شد", user=request.user, database=ws)
    messages.success(request, "ذخیره شد." if request.POST.get("do") != "enable" else "دریافت خودکار فعال شد؛ اولین دریافت در چند دقیقه‌ی آینده انجام می‌شود.")
    return back


@login_required
@require_POST
def source_run(request, pk, plugin, page, key):
    """دریافت دستی یک‌بار (حداکثر هر ۵ دقیقه)."""
    ws, spec, item, back = _source_target(request, pk, plugin, page, key)
    err = sources.run_now(ws, plugin, spec, item, request.user)
    (messages.error if err else messages.success)(request, err or "دریافت انجام شد.")
    return back


# ---------------------------------------------------------------------- ویرایش و حذف ردیف (`[[records]]`)
def _record_target(request, pk, plugin, page, key, rid):
    spec = pagekit.get(plugin, page)
    rc = pagekit.get_record(spec, key) if spec else None
    if rc is None:
        raise Http404
    ws = workspace.get(request, pk, spec.need)
    if not entitlements.allowed(plugin, user=request.user, ws=ws) or not caps.allowed("draw", user=request.user, ws=ws):
        raise Http404
    if not ws.is_live:
        raise Http404
    return ws, spec, rc, redirect(f"{reverse('kernel:page', kwargs={'pk': ws.pk, 'plugin': plugin, 'page': page})}#record-{key}")


@login_required
def record_edit(request, pk, plugin, page, key, rid):
    """فرم ویرایش یک ردیف (GET پر می‌کند، POST با UPDATE پارامتری ذخیره می‌کند)."""
    ws, spec, rc, back = _record_target(request, pk, plugin, page, key, rid)
    if request.method == "POST":
        values, errors = pagekit.read_form(rc, request.POST)
        if not errors:
            try:
                pagekit.update_record(ws, rc, rid, values)
            except pagekit.SpecError as exc:
                errors = [str(exc)]
            except Exception as exc:  # noqa: BLE001
                msg = str(exc).splitlines()[0][:200] if str(exc) else type(exc).__name__
                errors = ["ذخیره انجام نشد: " + ("زمان اجرا تمام شد." if "statement timeout" in msg else "داده با ساختار جدول نمی‌خواند.")]
                workspace.log_event("plugin_record", f"{plugin}/{page}/{key}#{rid}: {msg}", user=request.user, database=ws, success=False)
        if not errors:
            workspace.log_event("plugin_record", f"{plugin}/{page}/{key}: ردیف {rid} در {rc.table} ویرایش شد", user=request.user, database=ws)
            messages.success(request, "ردیف ذخیره شد.")
            return back
        for e in errors:
            messages.error(request, e)
        current = {f.name: request.POST.get(f"f_{f.name}", "") for f in rc.fields}
    else:
        try:
            current = pagekit.fetch_record(ws, rc, rid)
        except pagekit.SpecError as exc:
            messages.error(request, str(exc))
            return back
        if current is None:
            raise Http404
        current = {k: ("" if v is None else v) for k, v in current.items()}
    fields = [{"fd": f, "val": current.get(f.name, "")} for f in rc.fields]
    return render(request, "kernel/record_edit.html", {"db": ws, "page": spec, "rc": rc, "rid": rid, "fields": fields, "section": "pages",
                                                      "has_draw": any(f.kind == "geometry" for f in rc.fields), "back_url": back.url})


@login_required
@require_POST
def record_delete(request, pk, plugin, page, key, rid):
    ws, _spec, rc, back = _record_target(request, pk, plugin, page, key, rid)
    if not rc.can_delete:
        raise Http404
    try:
        pagekit.delete_record(ws, rc, rid)
    except pagekit.SpecError as exc:
        messages.error(request, str(exc))
        return back
    workspace.log_event("plugin_record", f"{plugin}/{page}/{key}: ردیف {rid} از {rc.table} حذف شد", user=request.user, database=ws)
    messages.success(request, "ردیف حذف شد.")
    return back


# ---------------------------------------------------------------------- گزارش PDF و تصویر (`[[reports]]`)
REPORT_PER_MIN, PREVIEW_PER_MIN, MAX_LAYOUT_BYTES = 6, 40, 100_000


def _rate(prefix: str, user, limit: int) -> bool:
    """True اگر در همین دقیقه از سقف نگذشته."""
    from django.core.cache import cache

    ck = f"{prefix}:{user.pk}"
    cache.add(ck, 0, 60)
    try:
        return cache.incr(ck) <= limit
    except ValueError:
        return True


def _report_target(request, pk, plugin, page, key, *, write: bool = False):
    spec = pagekit.get(plugin, page)
    rp = pagekit.get_report(spec, key) if spec else None
    if rp is None:
        raise Http404
    need = spec.need if not write or spec.need == "owner" else "editor"
    ws = workspace.get(request, pk, need)
    if not entitlements.allowed(plugin, user=request.user, ws=ws) or not caps.allowed("reports", user=request.user, ws=ws):
        raise Http404
    return ws, spec, rp


def _report_layout(ws, plugin, spec, rp):
    """(چیدمان، ردیف ذخیره‌شده یا None). چیدمان خراب ذخیره‌شده به پیش‌فرض برمی‌گردد."""
    from . import reportlayout
    from .models import ReportLayout

    row = ReportLayout.objects.filter(workspace_id=ws.pk, plugin_id=plugin, page=spec.key, key=rp.key).first()
    if row is not None:
        try:
            return reportlayout.validate(row.layout, len(spec.blocks)), row
        except ValueError:
            pass
    return reportlayout.default_layout(rp, len(spec.blocks)), row


def _report_values(request, ws, spec):
    layers = {}
    if any(p.kind == "layer" for p in spec.params):
        try:
            layers = {f"{t.schema}.{t.name}": t.name for t in tenantdb.catalog(ws).tables()}
        except tenantdb.TenantError:
            layers = {}
    return pagekit.read_values(spec, request.GET, layers)


def _report_html(request, ws, spec, rp, layout, row, *, preview: bool):
    """(html، logo bytes، mime)؛ بلوک‌های استفاده‌شده را با فیلترهای درخواست می‌سازد."""
    from django.utils import timezone

    from . import reportlayout

    values, errors = _report_values(request, ws, spec)
    if errors:
        raise reports.ReportError(errors[0])
    blocks = {i: pagekit.render_block(ws, spec, spec.blocks[i - 1], values) for i in reportlayout.referenced_blocks(layout)}
    filters = [f"{p.label}: {values.get(p.name)}" for p in spec.params if values.get(p.name) not in (None, "")]
    logo = bytes(row.logo) if row is not None and row.logo else None
    mime = row.logo_mime if row is not None else ""
    if logo:
        import base64

        src = f"data:{mime};base64,{base64.b64encode(logo).decode()}" if preview else reports.LOGO_URL
    else:
        src = ""
    html = reports.build_html(layout=layout, doc_title=rp.title, page_title=spec.title, blocks=blocks, site_name=workspace_site_name(),
                              db_label=getattr(ws, "db_name", "") or str(ws.pk), filters=filters, now=timezone.now(), logo_src=src,
                              preview=preview)
    return html, logo, mime or "image/png"


def _report_export(request, pk, plugin, page, key, fmt: str):
    """خروجی گزارش با چیدمان ذخیره‌شده: PDF یا تصویر PNG یک صفحه (`?page=N`). فقط‌خواندنی؛ سقف نرخ و مصرف."""
    from django.utils import timezone

    ws, spec, rp = _report_target(request, pk, plugin, page, key)
    back = redirect("kernel:page", pk=ws.pk, plugin=plugin, page=page)
    if not ws.is_live:
        messages.error(request, "گزارش فقط برای پایگاه داده‌ی فعال ساخته می‌شود.")
        return back
    if not _rate("report-rate", request.user, REPORT_PER_MIN):
        messages.error(request, "درخواست گزارش زیاد بود؛ یک دقیقه بعد دوباره تلاش کنید.")
        return back
    within, _now, cap = metering.check(plugin, "report_pdfs", user=request.user, ws=ws)
    if not within:
        messages.error(request, f"سقف ماهانه‌ی گزارش ({cap}) پر شده است.")
        return back
    layout, row = _report_layout(ws, plugin, spec, rp)
    try:
        html, logo, mime = _report_html(request, ws, spec, rp, layout, row, preview=False)
        pdf = reports.to_pdf(html, rp.title, logo=logo, logo_mime=mime)
        if fmt == "png":
            n = request.GET.get("page", "1")
            data = reports.pdf_to_png(pdf, int(n) if n.isdigit() else 1)
    except reports.ReportError as exc:
        messages.error(request, str(exc))
        return back
    metering.record(plugin, "report_pdfs", user=request.user, ws=ws)
    workspace.log_event("plugin_report", f"{plugin}/{page}/{key}: گزارش {fmt.upper()} ساخته شد", user=request.user, database=ws)
    stamp = f"{timezone.localdate():%Y%m%d}"
    if fmt == "png":
        resp = HttpResponse(data, content_type="image/png")
        resp["Content-Disposition"] = f'attachment; filename="report-{key}-{stamp}.png"'
    else:
        resp = HttpResponse(pdf, content_type="application/pdf")
        resp["Content-Disposition"] = f'attachment; filename="report-{key}-{stamp}.pdf"'
    resp["Cache-Control"] = "no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
def report_pdf(request, pk, plugin, page, key):
    return _report_export(request, pk, plugin, page, key, "pdf")


@login_required
def report_png(request, pk, plugin, page, key):
    return _report_export(request, pk, plugin, page, key, "png")


@login_required
def report_editor(request, pk, plugin, page, key):
    """ویرایشگر چیدمان گزارش (سطح ویرایشگر): فهرست عنصرها، ویژگی‌ها، پیش‌نمایش و ذخیره."""
    from . import reportlayout

    ws, spec, rp = _report_target(request, pk, plugin, page, key, write=True)
    layout, row = _report_layout(ws, plugin, spec, rp)
    q = request.GET.urlencode()
    base = {"pk": ws.pk, "plugin": plugin, "page": page, "key": key}
    ctx = {"db": ws, "page": spec, "rp": rp, "section": "pages", "has_logo": bool(row is not None and row.logo),
           "layout_json": layout,
           "blocks_json": [{"index": i, "kind": b.kind, "title": b.title or {"kpi": "شمارنده", "table": "جدول", "bars": "نمودار", "map": "نقشه", "text": "متن"}.get(b.kind, b.kind)}
                           for i, b in enumerate(spec.blocks, 1)],
           "types_json": reportlayout.TYPE_LABELS, "query": q,
           "urls": {"save": reverse("kernel:report_save", kwargs=base), "preview": reverse("kernel:report_preview", kwargs=base) + (f"?{q}" if q else ""),
                    "logo": reverse("kernel:report_logo", kwargs=base), "back": reverse("kernel:page", kwargs={k: base[k] for k in ("pk", "plugin", "page")}) + (f"?{q}" if q else ""),
                    "pdf": reverse("kernel:report", kwargs=base) + (f"?{q}" if q else ""), "png": reverse("kernel:report_png", kwargs=base) + (f"?{q}" if q else "")}}
    return render(request, "kernel/report_editor.html", ctx)


def _json_body(request):
    import json

    if len(request.body) > MAX_LAYOUT_BYTES:
        raise ValueError("چیدمان بیش از حد بزرگ است.")
    try:
        return json.loads(request.body or b"{}")
    except ValueError:
        raise ValueError("درخواست نامعتبر است.") from None


@login_required
@require_POST
def report_save(request, pk, plugin, page, key):
    from . import reportlayout
    from .models import ReportLayout

    ws, spec, rp = _report_target(request, pk, plugin, page, key, write=True)
    try:
        body = _json_body(request)
        layout = reportlayout.validate(body.get("layout") if body.get("layout") is not None else body, len(spec.blocks)) if body.get("reset") is not True \
            else reportlayout.default_layout(rp, len(spec.blocks))
    except (ValueError, AttributeError) as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    ReportLayout.objects.update_or_create(workspace_id=ws.pk, plugin_id=plugin, page=page, key=key,
                                          defaults={"layout": layout, "updated_by": request.user})
    workspace.log_event("plugin_report", f"{plugin}/{page}/{key}: چیدمان گزارش ذخیره شد", user=request.user, database=ws)
    return JsonResponse({"ok": True, "layout": layout})


@login_required
@require_POST
@xframe_options_sameorigin  # پیش‌نمایش داخل iframe همین سایت باز می‌شود؛ سایت پیش‌فرض DENY است
def report_preview(request, pk, plugin, page, key):
    """پیش‌نمایش HTML همان چیدمانِ ذخیره‌نشده (برای iframe بدون اسکریپت)؛ همان داده و فیلترها."""
    from . import reportlayout

    ws, spec, rp = _report_target(request, pk, plugin, page, key, write=True)
    if not ws.is_live:
        return HttpResponse("پایگاه فعال نیست.", status=409)
    if not _rate("report-preview", request.user, PREVIEW_PER_MIN):
        return HttpResponse("پیش‌نمایش زیاد بود؛ کمی صبر کنید.", status=429)
    try:
        if "layout_json" in request.POST:  # فرم هدف‌گرفته به iframe (CSP جداگانه‌ی پاسخ)
            import json

            raw = request.POST["layout_json"]
            if len(raw) > MAX_LAYOUT_BYTES:
                raise ValueError("چیدمان بیش از حد بزرگ است.")
            layout = reportlayout.validate(json.loads(raw), len(spec.blocks))
        else:
            layout = reportlayout.validate(_json_body(request).get("layout"), len(spec.blocks))
    except (ValueError, AttributeError) as exc:
        return HttpResponse("چیدمان نامعتبر است: " + str(exc), status=400)
    _l, row = _report_layout(ws, plugin, spec, rp)
    try:
        html, _logo, _mime = _report_html(request, ws, spec, rp, layout, row, preview=True)
    except reports.ReportError as exc:
        return HttpResponse(str(exc), status=400)
    resp = HttpResponse(html, content_type="text/html; charset=utf-8")
    resp["Content-Security-Policy"] = "default-src 'none'; img-src data:; style-src 'unsafe-inline'; font-src data:; frame-ancestors 'self'"
    resp["Cache-Control"] = "no-store"
    resp["X-Content-Type-Options"] = "nosniff"
    return resp


@login_required
@require_POST
def report_logo(request, pk, plugin, page, key):
    """بارگذاری یا حذف لوگو (فقط PNG/JPEG؛ بازکدگذاری با Pillow)."""
    from . import reportlayout
    from .models import ReportLayout

    ws, _spec, _rp = _report_target(request, pk, plugin, page, key, write=True)
    row, _c = ReportLayout.objects.get_or_create(workspace_id=ws.pk, plugin_id=plugin, page=page, key=key)
    if request.POST.get("do") == "delete":
        row.logo, row.logo_mime = None, ""
        row.save(update_fields=["logo", "logo_mime", "updated_at"])
        return JsonResponse({"ok": True, "has_logo": False})
    f = request.FILES.get("logo")
    if f is None:
        return JsonResponse({"ok": False, "error": "فایلی انتخاب نشده است."}, status=400)
    try:
        data, mime = reportlayout.process_logo(f.read(reportlayout.MAX_LOGO_BYTES + 1))
    except ValueError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    row.logo, row.logo_mime, row.updated_by = data, mime, request.user
    row.save()
    workspace.log_event("plugin_report", f"{plugin}/{page}/{key}: لوگوی گزارش تغییر کرد", user=request.user, database=ws)
    return JsonResponse({"ok": True, "has_logo": True})


def workspace_site_name() -> str:
    from django.conf import settings

    return getattr(settings, "SITE_NAME", "") or "ژئوپایگاه"
