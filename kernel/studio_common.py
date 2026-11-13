"""کمک‌تابع‌های مشترک استودیوی دیداری و ورود پلاگین‌های قبلی (docs/adr/0010، مرحله‌ی ۱۱): دسترسی، ذخیره‌ی نقشه با ساخت صفحه‌ها،
نوع ستون‌ها، آیکون‌ها و اجرای آزمون handler. (پیش‌تر در ویزارد قدیمی `wizard_admin` بود که حذف شد.)"""
from __future__ import annotations

from . import pkgtest, wizard, wizard_code
from .models import PluginDraft

ICON_CHOICES = ("chart", "pulse", "gauge", "table", "pin", "layers", "satellite", "bell", "globe", "db", "clock", "bolt")
COL_TYPES = (("lat", "عرض جغرافیایی (−۹۰ تا ۹۰)"), ("lon", "طول جغرافیایی (−۱۸۰ تا ۱۸۰)"), ("text", "متن"), ("integer", "عدد صحیح"), ("bigint", "عدد صحیح بزرگ"), ("double", "عدد اعشاری"), ("boolean", "بله/خیر"),
             ("date", "تاریخ"), ("timestamptz", "زمان"), ("jsonb", "JSON"), ("point", "نقطه‌ی مکانی"), ("line", "خط"), ("polygon", "چندضلعی"), ("multipolygon", "چندچندضلعی"))

ROLE_RUN = {"block": "block", "alert": "block", "importer": "import", "exporter": "export", "ingest": "ingest"}


def allowed(request) -> bool:
    return request.user.has_perm("kernel.upload_pluginrelease")


def save(draft: PluginDraft, spec: dict, user) -> str:
    """مشخصات را ذخیره و صفحه‌ها را از رویش می‌سازد؛ متن خطای ساخت یا ''."""
    draft.wizard = spec
    draft.updated_by = user
    err = ""
    code = spec.get("code") or {}
    draft.code = {n: h.get("source", "") for n, h in code.items()}
    draft.tests = {n: h.get("test", "") for n, h in code.items()}
    draft.alerts = {n: h["every"] for n, h in code.items() if h.get("role") == "alert" and isinstance(h.get("every"), int)}
    try:
        wizard_code.validate_code(spec)
        draft.pages = wizard.compile_pages(draft.plugin_id, spec)
    except wizard.WizardError as exc:
        err = str(exc)
    draft.save()
    return err



def runner_ready() -> bool:
    from .runner import client

    return client.mode() in ("local", "remote")



def test_results(name: str, h: dict) -> list[dict]:
    """آزمون‌های یک handler در runner (همان آزمون بسته)؛ [{case, ok, message}]. TestSpecError اگر ساختار آزمون نامعتبر یا runner خاموش است."""
    from types import SimpleNamespace

    cases = pkgtest.parse(h.get("test", ""), name)
    role = ROLE_RUN.get(h.get("role", "block"), "block")
    spec = SimpleNamespace(format="txt", max_rows=1000, table="", fields=()) if role == "export" else None
    if role == "ingest":
        role = "block"  # ساختار ردیف‌ها را بلوک نمی‌داند؛ شمار ردیف‌ها سنجیده می‌شود
    out = []
    for c in cases:
        msg = pkgtest.run_case(name, h.get("source", ""), role, spec, c)
        out.append({"case": c.name, "ok": not msg, "message": msg})
    return out



