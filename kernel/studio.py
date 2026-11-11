"""استودیوی ساخت پلاگین اعلانی: از پیش‌نویس (فرم) تا بررسی زنده، پیش‌نمایش روی یک پایگاه داده و خروجی آماده‌ی امضا.

- پیش‌نویس هیچ‌وقت امضا نمی‌شود: کلید ناشر عمداً روی سرور نیست (docs/plugins/packages.md). خروجی یک پوشه‌ی zip است که با
  `manage.py plugin_pack` در CI امضا و بعد بارگذاری می‌شود؛ پس استودیو راهی برای دور زدن امضا و اصل دونفره نیست.
- بررسی همان بررسی بسته است (مانیفست، شناسه، صفحه‌ها)، بدون مرحله‌ی امضا.
"""
from __future__ import annotations

import io
import json
import tomllib
import zipfile

from . import pagekit, pkg
from .plugins import registry

TEMPLATES = {
    "monitor": ('''key = "{key}"
title = "پایش"
subtitle = "نمای کلی داده‌ها"
icon = "chart"
group = "data"
need = "viewer"
order = 100

[[params]]
name = "t"
kind = "layer"
label = "جدول"

[[blocks]]
kind = "kpi"
title = "تعداد ردیف"
sql = "select count(*) from {{t}}"
unit = "ردیف"

[[blocks]]
kind = "table"
title = "نمونه‌ی داده"
sql = "select * from {{t}} limit 50"
''', "پایش ساده: شمارنده و جدول نمونه"),
    "form": ('''key = "{key}"
title = "ثبت"
subtitle = "ثبت یک ردیف"
icon = "plus"
group = "manage"
need = "editor"
order = 100

[[blocks]]
kind = "text"
text = "مقادیر را وارد کنید."

[[forms]]
key = "main"
title = "ردیف تازه"
table = "my_table"

[[forms.fields]]
name = "title"
kind = "text"
label = "عنوان"
required = true
max = 80
''', "فرم ثبت ردیف (نیازمند جدول مقصد)"),
}


def manifest_text(d) -> str:
    q = json.dumps  # رشته‌ی JSON معتبر TOML هم هست
    req = [r.strip() for r in (d.requires or "").split(",") if r.strip()]
    pages = ", ".join(q(f"pages/{k}.toml") for k in sorted(d.pages))
    return (f"id = {q(d.plugin_id)}\nname = {q(d.name, ensure_ascii=False)}\nversion = {q(d.version)}\napi = 1\n"
            f"kind = {q(d.kind)}\ntier = 1\nrequires = [{', '.join(q(r) for r in req)}]\n\n[contributes]\npages = [{pages}]\n")


def files_of(d) -> dict[str, bytes]:
    files = {pkg.MANIFEST_NAME: manifest_text(d).encode()}
    for key, text in sorted(d.pages.items()):
        files[f"pages/{key}.toml"] = str(text).encode()
    if (d.readme or "").strip():
        files["README.md"] = d.readme.encode()
    return files


def check(d) -> list[dict]:
    """بررسی پیش‌نویس مثل بررسی بسته (بدون امضا و بدون شرط «نسخه‌ی بالاتر»): [{stage, ok, detail}]."""
    steps: list[dict] = []

    def stage(name, fn):
        try:
            out = fn()
        except (pkg.PackageError, ValueError) as exc:
            steps.append({"stage": name, "ok": False, "detail": str(exc)})
            return None
        steps.append({"stage": name, "ok": True, "detail": ""})
        return out

    files = files_of(d)
    total = sum(len(v) for v in files.values())
    if stage("حجم و نام فایل‌ها", lambda: _sizes(files, total)) is None:
        return steps
    manifest = stage("مانیفست", lambda: pkg._manifest(files))
    if manifest is None:
        return steps
    if stage("هویت", lambda: pkg._identity(manifest, check_version=False)) is None:
        return steps
    pages = stage("مشخصات صفحه‌ها", lambda: pkg._pages(manifest, files))
    if pages:
        writes = sorted({f"{pg.key}→{fm.table}" for pg in pages for fm in pg.forms})
        steps.append({"stage": "دسترسی نوشتن", "ok": True,
                      "detail": ("فقط INSERT در: " + "، ".join(writes)) if writes else "بدون نوشتن (فقط خواندنی)"})
    return steps


def _sizes(files: dict[str, bytes], total: int) -> bool:
    if len(files) > pkg.MAX_FILES:
        raise pkg.PackageError(f"حداکثر {pkg.MAX_FILES} فایل.")
    if total > pkg.MAX_TOTAL:
        raise pkg.PackageError("حجم کل بیش از حد مجاز است.")
    for n, b in files.items():
        if not pkg.NAME_RE.fullmatch(n):
            raise pkg.PackageError(f"نام فایل «{n}» مجاز نیست.")
        if len(b) > pkg.MAX_FILE:
            raise pkg.PackageError(f"فایل «{n}» بزرگ‌تر از حد مجاز است.")
    return True


def ok(steps: list[dict]) -> bool:
    return bool(steps) and all(s["ok"] for s in steps)


def export_zip(d) -> bytes:
    """پوشه‌ی بدون امضا برای `plugin_pack` (نه خود بسته)."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files_of(d).items():
            z.writestr(name, data)
    return buf.getvalue()


def parse_pages(d) -> list[pagekit.Page]:
    out = []
    for _key, text in sorted(d.pages.items()):
        spec = tomllib.loads(text)
        out.append(pagekit.parse_page(d.plugin_id, spec))
    return out


def preview_page(d, key: str, ws, query) -> dict:
    """بلوک‌های یک صفحه‌ی پیش‌نویس را روی پایگاه داده‌ی انتخابی (فقط‌خواندنی، نقش محدود) رندر می‌کند.
    فرم‌ها اجرا نمی‌شوند. پیام خطا به‌جای استثنا برمی‌گردد."""
    from . import tenantdb

    pages = {p.key: p for p in parse_pages(d)}
    page = pages.get(key)
    if page is None:
        raise ValueError("صفحه‌ای با این کلید نیست.")
    layers: dict[str, str] = {}
    if any(p.kind == "layer" for p in page.params):
        layers = {f"{t.schema}.{t.name}": t.name for t in tenantdb.catalog(ws).tables()}
    values, errors = pagekit.read_values(page, query, layers)
    blocks = [pagekit.render_block(ws, page, b, values) for b in page.blocks]
    return {"page": page, "blocks": blocks, "values": values, "layers": layers, "param_errors": errors,
            "has_map": any(b["kind"] == "map" for b in blocks)}


def installed(plugin_id: str) -> bool:
    return plugin_id in registry.plugins
