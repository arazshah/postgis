"""API JSON استودیوی دیداری پلاگین (docs/adr/0010): وضعیت نقشه، عملیات، پیش‌نمایش نمونه، تاریخچه و بازگشت.

مرورگر فقط عملیات ساخت‌یافته می‌فرستد (kernel.blueprint)؛ هسته نقشه را می‌سنجد، ذخیره و صفحه‌های TOML را از رویش می‌سازد
(همان `wizard_admin._save` و `wizard.compile_pages`). پیش‌نمایش نمونه (kernel.sampledata) هیچ پایگاه داده‌ای را نمی‌خواند.
دسترسی همان مجوز ویزارد است (`kernel.upload_pluginrelease`).
"""
from __future__ import annotations

import copy
import json

from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.template.loader import render_to_string
from django.views.decorators.http import require_GET, require_POST

from . import ai, blueprint, pagekit, pkgtest, quality, sampledata, stepup, studio_ai, wizard, wizard_admin, wizard_code
from . import workspace as ws_mod
from .models import PluginDraft, PluginDraftRevision

MAX_BODY = 200_000


def _draft(request, pk) -> PluginDraft:
    if not wizard_admin._allowed(request):
        raise PermissionDenied
    return get_object_or_404(PluginDraft, pk=pk)


def _spec(draft: PluginDraft) -> dict:
    spec = copy.deepcopy(draft.wizard) if draft.wizard else blueprint.empty()
    return blueprint.ensure_ids(spec)


def _state(draft: PluginDraft, spec: dict, save_error: str = "") -> dict:
    return {"spec": spec, "plugin_id": draft.plugin_id, "name": draft.name, "version": draft.version,
            "analysis": blueprint.analyze(spec, draft.plugin_id), "quality": quality.evaluate(spec, draft.plugin_id), "save_error": save_error,
            "revision": PluginDraftRevision.objects.filter(draft=draft).values_list("id", flat=True).first()}


def _record(draft: PluginDraft, spec: dict, label: str, user) -> None:
    PluginDraftRevision.objects.create(draft=draft, spec=spec, label=label[:120], user=user if getattr(user, "pk", None) else None)
    keep = list(PluginDraftRevision.objects.filter(draft=draft).values_list("id", flat=True)[: PluginDraftRevision.KEEP])
    PluginDraftRevision.objects.filter(draft=draft).exclude(id__in=keep).delete()


def _commit(request, draft: PluginDraft, spec: dict, label: str) -> dict:
    err = wizard_admin._save(draft, spec, request.user)
    _record(draft, spec, label, request.user)
    return _state(draft, spec, err)


def _body(request) -> dict:
    if len(request.body) > MAX_BODY:
        raise blueprint.BlueprintError("درخواست بیش از حد بزرگ است.")
    try:
        data = json.loads(request.body or b"{}")
    except ValueError:
        raise blueprint.BlueprintError("بدنه‌ی درخواست JSON معتبر نیست.") from None
    if not isinstance(data, dict):
        raise blueprint.BlueprintError("بدنه‌ی درخواست باید یک شیء باشد.")
    return data


@require_GET
def state(request, pk):
    draft = _draft(request, pk)
    spec = _spec(draft)
    if not PluginDraftRevision.objects.filter(draft=draft).exists():
        _record(draft, spec, "آغاز", request.user)  # نقطه‌ی بازگشت اولیه
    return JsonResponse(_state(draft, spec))


@require_POST
def op(request, pk):
    """{"op": ...} یا {"ops": [...]}؛ موفق: وضعیت تازه. خطای ساختاری: ۴۰۰ با پیام و نقشه دست‌نخورده."""
    draft = _draft(request, pk)
    try:
        data = _body(request)
        spec = _spec(draft)
        if "ops" in data:
            new = blueprint.apply_all(spec, draft.plugin_id, data["ops"])
            label = f"دسته‌ی {len(data['ops'])} عملیات"
        else:
            new = blueprint.apply(spec, draft.plugin_id, data)
            label = str(data.get("op", ""))
    except blueprint.BlueprintError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_commit(request, draft, new, label))


@require_GET
def preview(request, pk, page):
    """نمای نمونه‌ی یک صفحه: HTML هر بلوک جدا (برای بوم) و HTML کل صفحه؛ با همان قالب صفحه‌ی مشتری."""
    draft = _draft(request, pk)
    spec = _spec(draft)
    try:
        ctx = sampledata.preview(spec, page)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=404)
    items = []
    for b in ctx["all_blocks"]:
        if b["kind"] == "action":
            items.append({"id": b["id"], "kind": b["action"], "action": True, "title": b["title"], "html": "", "error": ""})
            continue
        html = render_to_string("kernel/_page_body.html", {"blocks": [b], "param_errors": []}, request=request)
        items.append({"id": b["id"], "kind": b["kind"], "action": False, "title": b["title"], "width": b["width"], "html": html,
                      "error": b.get("error", ""), "placeholder": bool(b.get("placeholder"))})
    return JsonResponse({"blocks": items, "sample": True})


@require_POST
def assistant(request, pk):
    """یک نوبت گفتگو با دستیار: {message, history?, mode?, page?, selected?} ← {reply, ops, summary, valid, error, issues_*}.
    دستیار فقط پیشنهاد می‌دهد؛ اعمال از `api/op/` با تأیید کاربر است. فقط ساختار نقشه به مدل می‌رسد."""
    draft = _draft(request, pk)
    try:
        data = _body(request)
    except blueprint.BlueprintError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    if not ai.available():
        return JsonResponse({"error": "دستیار تنظیم نشده است؛ آدرس و کلید API را در تنظیمات سایت ← دستیار هوشمند بگذارید."}, status=400)
    try:
        out = studio_ai.ask(request.user, _spec(draft), draft.plugin_id, str(data.get("message", "")), history=data.get("history"),
                            mode=str(data.get("mode") or "chat"), page=str(data.get("page") or "")[:40], selected=str(data.get("selected") or "")[:20],
                            focus=str(data.get("focus") or "")[:40], failures=str(data.get("failures") or "")[:studio_ai.MAX_FAILURES])
    except ai.AiError as exc:
        return JsonResponse({"error": str(exc)}, status=429 if "سقف" in str(exc) else 400)
    ws_mod.log_event("plugin_studio_ai", f"{draft.plugin_id}: {data.get('mode') or 'chat'}، {len(out['ops'])} پیشنهاد" + ("" if out["valid"] else " (نامعتبر)"), user=request.user)
    return JsonResponse(out)


def _runner_error() -> str:
    from .runner import client

    if client.mode() not in ("local", "remote"):
        return "اجرای کد در این استقرار خاموش است. از «پلاگین‌ها ← پیشرفته ← کلیدهای ناشر و اجرای کد» حالت «راه‌دور» را روشن کنید."
    return ""


@require_POST
def run(request, pk):
    """اجرای آزمون‌های اعلانی یا اجرای آزمایشی یک handler در runner (نیازمند تأیید تازه‌ی ورود دومرحله).
    {action: "tests"|"trial", name, params?, file_text?, database?}؛ چیزی در پایگاه مشتری نوشته نمی‌شود."""
    draft = _draft(request, pk)
    try:
        data = _body(request)
    except blueprint.BlueprintError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    h = ((draft.wizard or {}).get("code") or {}).get(str(data.get("name", "")))
    if h is None:
        return JsonResponse({"error": "handler پیدا نشد."}, status=404)
    if not stepup.ok(request):
        return JsonResponse({"error": "برای اجرا تأیید تازه‌ی ورود دومرحله لازم است.", "stepup": stepup.url(request)}, status=403)
    if msg := _runner_error():
        return JsonResponse({"error": msg}, status=400)
    name = data["name"]
    if data.get("action") == "tests":
        try:
            results = wizard_admin._test_results(name, h)
        except (pkgtest.TestSpecError, wizard.WizardError) as exc:
            return JsonResponse({"error": f"آزمون: {exc}"}, status=400)
        except Exception as exc:  # noqa: BLE001 - خطای runner
            return JsonResponse({"error": f"آزمون اجرا نشد: {str(exc)[:200]}"}, status=400)
        return JsonResponse({"results": results, "ok": bool(results) and all(r["ok"] for r in results)})
    if data.get("action") != "trial":
        return JsonResponse({"error": "عمل نامعتبر است."}, status=400)
    return _trial(request, draft, name, h, data)


def _trial(request, draft, name, h, data):
    from . import pluginio
    from .runner import client

    params = data.get("params") or {}
    if not isinstance(params, dict):
        return JsonResponse({"error": "ورودی باید یک شیء JSON باشد."}, status=400)
    file_text = data.get("file_text")
    file = file_text.encode() if isinstance(file_text, str) and file_text else None
    pkv = data.get("database")
    ws = ws_mod.peek(int(pkv)) if str(pkv or "").isdigit() else None
    if pkv not in (None, "") and (ws is None or not getattr(ws, "is_live", False)):
        return JsonResponse({"error": "پایگاه داده‌ی فعال با این شناسه نیست."}, status=400)
    role = wizard_admin.ROLE_RUN.get(h.get("role", "block"), "block")
    logs: list[str] = []
    sql_fn = (lambda q, a: pagekit.read_select(ws, q, a)) if ws is not None else None  # noqa: E731
    try:
        out = client.run_files({f"code/{name}.py": h["source"]}, name, params, sql_fn, getattr(ws, "pk", 0) or 0, file=file,
                               io=role != "block", on_log=logs.append, allow_no_ws=True, plugin="studio")
        if role == "import":
            t = pluginio.normalize_import("trial_table", out)
            verdict = f"ورود معتبر است: {len(t.rows):,} ردیف، {len(t.columns)} ستون" + ("، با ستون مکانی" if t.geometry else "")
        elif role == "export":
            fname, body, _ctype = pluginio.normalize_export(out, "txt")
            verdict = f"خروجی معتبر است: {fname} ({len(body):,} بایت)"
        elif role == "ingest":
            verdict = f"{len(out.get('rows', [])):,} ردیف تبدیل شد." if isinstance(out, dict) and isinstance(out.get("rows"), list) else "خروجی باید {rows: [...]} باشد."
        else:
            verdict = "اجرا موفق بود."
    except client.RunnerError as exc:
        return JsonResponse({"ok": False, "error": str(exc), "logs": logs})
    except pluginio.PluginIOError as exc:
        return JsonResponse({"ok": False, "error": f"خروجی معتبر نیست: {exc}", "logs": logs})
    shown = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    ws_mod.log_event("plugin_studio", f"اجرای آزمایشی استودیو {draft.plugin_id}/{name}", user=request.user, database=ws)
    return JsonResponse({"ok": True, "verdict": verdict, "result": shown if len(shown) <= 6000 else shown[:6000] + "\n… (کوتاه‌شده)", "logs": logs})


def designer(request, pk):
    """صفحه‌ی استودیوی دیداری؛ همه‌ی کار با API همین ماژول انجام می‌شود."""
    from django.shortcuts import render
    from django.urls import reverse

    draft = _draft(request, pk)
    api = {n: reverse(f"admin:kernel_plugindraft_api_{n}", args=[draft.pk]) for n in ("state", "op", "revisions", "restore", "run", "assistant")}
    tpl = [{"key": k, "role": t["role"], "title": t["title"], "hint": t["hint"], "needs": t["needs"], "nums": t.get("nums", [])} for k, t in wizard_code.TEMPLATES.items()]
    codeinfo = {"templates": tpl, "roles": wizard_code.ROLE_LABEL, "cols": {k: [v[0], list(v[1])] for k, v in wizard_code.COLS.items()},
                "nums": {k: v[0] for k, v in wizard_code.NUMS.items()}, "runner_ready": not _runner_error(), "ai_ready": ai.available()}
    api["preview"] = reverse("admin:kernel_plugindraft_api_preview", args=[draft.pk, "__PAGE__"])
    return render(request, "admin/kernel/designer.html", {
        "draft": draft, "api": api, "codeinfo": codeinfo, "icons": wizard_admin.ICON_CHOICES, "col_types": wizard_admin.COL_TYPES,
        "links": {"hub": reverse("admin:kernel_plugindraft_changelist"), "publish": reverse("admin:kernel_plugindraft_wizard", args=[draft.pk, 5]),
                  "toml": reverse("admin:kernel_plugindraft_studio", args=[draft.pk]), "code": reverse("admin:kernel_plugindraft_wizard", args=[draft.pk, 3])}})


@require_GET
def revisions(request, pk):
    draft = _draft(request, pk)
    rows = PluginDraftRevision.objects.filter(draft=draft).select_related("user")[:PluginDraftRevision.KEEP]
    return JsonResponse({"revisions": [{"id": r.id, "label": r.label, "at": r.created_at.isoformat(),
                                        "user": getattr(r.user, "get_username", lambda: "")() if r.user else ""} for r in rows]})


@require_POST
def restore(request, pk):
    """بازگرداندن نقشه به یک نسخه (خودِ بازگشت هم نسخه‌ی تازه می‌شود، پس برگشت‌پذیر است)."""
    draft = _draft(request, pk)
    try:
        rid = int(_body(request).get("revision"))
    except (TypeError, ValueError, blueprint.BlueprintError):
        return JsonResponse({"error": "شناسه‌ی نسخه نامعتبر است."}, status=400)
    rev = get_object_or_404(PluginDraftRevision, pk=rid, draft=draft)
    return JsonResponse(_commit(request, draft, blueprint.ensure_ids(copy.deepcopy(rev.spec)), f"بازگشت به نسخه‌ی {rev.pk}"))


