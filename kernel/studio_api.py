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

from . import blueprint, sampledata, wizard_admin
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
            "analysis": blueprint.analyze(spec, draft.plugin_id), "save_error": save_error,
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


def designer(request, pk):
    """صفحه‌ی استودیوی دیداری؛ همه‌ی کار با API همین ماژول انجام می‌شود."""
    from django.shortcuts import render
    from django.urls import reverse

    draft = _draft(request, pk)
    api = {n: reverse(f"admin:kernel_plugindraft_api_{n}", args=[draft.pk]) for n in ("state", "op", "revisions", "restore")}
    api["preview"] = reverse("admin:kernel_plugindraft_api_preview", args=[draft.pk, "__PAGE__"])
    return render(request, "admin/kernel/designer.html", {
        "draft": draft, "api": api, "icons": wizard_admin.ICON_CHOICES, "col_types": wizard_admin.COL_TYPES,
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


