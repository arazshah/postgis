"""استودیوی ساخت پلاگین اعلانی: از پیش‌نویس (فرم) تا بررسی زنده، پیش‌نمایش روی یک پایگاه داده و خروجی آماده‌ی امضا.

- پیش‌نویس هیچ‌وقت امضا نمی‌شود: کلید ناشر عمداً روی سرور نیست (docs/plugins/packages.md). خروجی یک پوشه‌ی zip است که با
  `manage.py plugin_pack` در CI امضا و بعد بارگذاری می‌شود؛ پس استودیو راهی برای دور زدن امضا و اصل دونفره نیست.
- بررسی همان بررسی بسته است (مانیفست، شناسه، صفحه‌ها)، بدون مرحله‌ی امضا.
"""
from __future__ import annotations

import contextlib
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


HANDLER_TEMPLATES = {
    "block": ('''def handle(ctx, params):
    # فقط SELECT/WITH؛ نتیجه {columns, rows}
    r = ctx.sql("select 1 as n")
    return {"columns": ["شاخص", "مقدار"], "rows": [["نمونه", r["rows"][0][0]]]}
''', "بلوک صفحه (kpi/table/bars)"),
    "importer": ('''def handle(ctx, params):
    # ctx.file() بایت فایل؛ هسته جدول تازه می‌سازد
    lines = ctx.file().decode("utf-8").splitlines()
    rows = []
    for line in lines:
        a, b = line.split(",")
        rows.append([a, float(b)])
    return {"columns": [{"name": "name", "type": "text"}, {"name": "value", "type": "double"}], "rows": rows}
''', "ورود فایل ← جدول تازه"),
    "exporter": ('''def handle(ctx, params):
    r = ctx.sql("select 1 as n")
    return {"filename": "report", "text": "n\\n" + str(r["rows"][0][0]) + "\\n"}
''', "خروجی اختصاصی (متن)"),
    "alert": ('''def handle(ctx, params):
    n = ctx.sql("select count(*) from information_schema.tables")["rows"][0][0]
    if n > 1000:
        return {"alerts": [{"title": "تعداد زیاد", "body": f"{n} مورد"}]}
    return {"alerts": []}
''', "هشدار دوره‌ای"),
}


HANDLER_TESTS = {
    "block": '''[[cases]]
name = "نمونه"
[[cases.sql]]
match = "select 1"
columns = ["n"]
rows = [[1]]
[cases.expect]
rows_count = 1
''',
    "importer": '''[[cases]]
name = "دو ردیف"
file = "a,1.5\\nb,2"
[cases.expect]
rows_count = 2
''',
    "exporter": '''[[cases]]
name = "نمونه"
[[cases.sql]]
match = "select 1"
columns = ["n"]
rows = [[1]]
[cases.expect]
text_contains = "1"
''',
    "alert": '''[[cases]]
name = "کم: هشدار نیست"
[[cases.sql]]
match = "information_schema"
columns = ["n"]
rows = [[5]]
[cases.expect]
alerts_count = 0

[[cases]]
name = "زیاد: هشدار"
[[cases.sql]]
match = "information_schema"
columns = ["n"]
rows = [[5000]]
[cases.expect]
alerts_count = 1
''',
}


def manifest_text(d) -> str:
    q = json.dumps  # رشته‌ی JSON معتبر TOML هم هست
    req = [r.strip() for r in (d.requires or "").split(",") if r.strip()]
    pages = ", ".join(q(f"pages/{k}.toml") for k in sorted(d.pages))
    code = sorted(getattr(d, "code", None) or {})
    summary = str(((getattr(d, "wizard", None) or {}).get("intro") or {}).get("summary", "")).strip()[:240]
    desc = f"description = {q(summary, ensure_ascii=False)}\n" if summary else ""
    out = (f"id = {q(d.plugin_id)}\nname = {q(d.name, ensure_ascii=False)}\nversion = {q(d.version)}\napi = 1\n{desc}"
           f"kind = {q(d.kind)}\ntier = {2 if code else 1}\nrequires = [{', '.join(q(r) for r in req)}]\n\n[contributes]\npages = [{pages}]\n")
    if code:
        out += f"handlers = [{', '.join(q(c) for c in code)}]\n"
        for h in code:
            mins = (getattr(d, "alerts", None) or {}).get(h)
            if isinstance(mins, int) and not isinstance(mins, bool):
                out += f"\n[[contributes.alerts]]\nhandler = {q(h)}\nevery_minutes = {mins}\n"
    return out


def files_of(d) -> dict[str, bytes]:
    files = {pkg.MANIFEST_NAME: manifest_text(d).encode()}
    for key, text in sorted(d.pages.items()):
        files[f"pages/{key}.toml"] = str(text).encode()
    for name, src in sorted((getattr(d, "code", None) or {}).items()):
        files[f"code/{name}.py"] = str(src).encode()
    for name, text in sorted((getattr(d, "tests", None) or {}).items()):
        files[f"tests/{name}.toml"] = str(text).encode()
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
    code = stage("کد سطح ۲ (بررسی ایستا)", lambda: pkg._code(manifest, files))
    if code is None:
        return steps
    if stage("هشدارهای دوره‌ای", lambda: pkg._alerts(manifest, code)) is None:
        return steps
    if stage("آزمون‌های بسته (ساختار)", lambda: pkg._tests(files, code)) is None:
        return steps
    pages = stage("مشخصات صفحه‌ها", lambda: pkg._pages(manifest, files, set(code)))
    if pages:
        writes = sorted({f"{pg.key}→{fm.table}" for pg in pages for fm in pg.forms} |
                        {f"{pg.key}→جدول تازه ({im.handler})" for pg in pages for im in pg.imports} |
                        {f"{pg.key}→{ig.table} (دریافت عمومی با توکن)" for pg in pages for ig in pg.ingests} |
                        {f"{pg.key}→{sx.table} (واکشی دوره‌ای از {sx.host}؛ نیازمند تأیید میزبان در پنل)" for pg in pages for sx in pg.sources} |
                        {f"{pg.key}→ساخت جدول {t.name}" for pg in pages for t in pg.tables})
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


@contextlib.contextmanager
def temp_handlers(d):
    """کد پیش‌نویس را فقط برای مدت پیش‌نمایش در رجیستری handler می‌گذارد (اگر پلاگین نصب نیست) و بعد برمی‌دارد."""
    from . import handlers

    added = []
    if d.plugin_id not in registry.plugins:
        for name, src in (getattr(d, "code", None) or {}).items():
            handlers.register(d.plugin_id, name, src)
            added.append(f"{d.plugin_id}:{name}")
    try:
        yield
    finally:
        for key in added:
            registry._points.get(handlers.POINT, {}).pop(key, None)


def sealed_zip(d) -> bytes:
    """بسته‌ی مهرشده‌ی «panel» برای انتشار مستقیم از ویزارد (kernel.pkg.seal)؛ همان قالب بسته‌ی امضاشده."""
    files = files_of(d)
    files[pkg.SIG_NAME] = pkg.seal(files)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items():
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


# ---------------------------------------------------------------------- اجرای آزمایشی handler
MAX_SHOWN = 20_000


def roles(d) -> dict[str, tuple[str, object]]:
    """نقش هر handler در صفحه‌های پیش‌نویس: ("import"، spec) | ("export"، spec) | ("block"، None)."""
    out: dict[str, tuple[str, object]] = {}
    try:
        pages = parse_pages(d)
    except Exception:  # noqa: BLE001 - صفحه‌ی خراب: نقش نامشخص
        return out
    for pg in pages:
        for b in pg.blocks:
            if b.handler:
                out.setdefault(b.handler, ("block", None))
        for im in pg.imports:
            out[im.handler] = ("import", im)
        for ex in pg.exports:
            out[ex.handler] = ("export", ex)
        for ig in pg.ingests:
            if ig.handler:
                out[ig.handler] = ("ingest", ig)
    return out


def trial(d, handler: str, params: dict, file: bytes | None = None, ws=None) -> dict:
    """handler پیش‌نویس را با ورودی نمونه اجرا می‌کند (از همان مسیر مدل‌آگاه runner؛ در حالت off اجرا نمی‌شود).

    بدون پایگاه داده‌ی انتخابی، `ctx.sql` خطای «دسترسی ندارد» می‌دهد. خروجی همان‌طور که هسته در کاربرد واقعی اعتبارسنجی می‌کند
    (ورود: ستون و نوع و ردیف؛ خروج: قالب و حجم) بررسی می‌شود تا نویسنده پیش از بارگذاری ایرادش را ببیند؛ **چیزی نوشته نمی‌شود**.
    dict: {ok, error, result (JSON خوانا، کوتاه‌شده)، verdict (فهرست پیام)، logs}.
    """
    from . import pagekit, pluginio
    from .runner import client

    res = {"ok": False, "error": "", "result": "", "verdict": [], "logs": []}
    src = (getattr(d, "code", None) or {}).get(handler)
    if src is None:
        res["error"] = "handler در پیش‌نویس نیست."
        return res
    from .runner import scan

    found = scan.scan(src, f"code/{handler}.py")
    if found:
        res["error"] = "کد از بررسی ایستا نمی‌گذرد: " + "؛ ".join(found[:3])
        return res
    role, spec = roles(d).get(handler, ("block", None))
    sql_fn = (lambda q, a: pagekit.read_select(ws, q, a)) if ws is not None else None
    try:
        out = client.run_files({f"code/{handler}.py": src}, handler, params, sql_fn, getattr(ws, "pk", 0) or 0, file=file,
                               io=role in ("import", "export", "ingest"), on_log=res["logs"].append, allow_no_ws=True, plugin="studio")
    except client.RunnerError as exc:
        res["error"] = str(exc)
        return res
    shown = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    res["result"] = shown if len(shown) <= MAX_SHOWN else shown[:MAX_SHOWN] + "\n… (کوتاه‌شده)"
    try:
        if role == "import":
            t = pluginio.normalize_import("trial_table", out)
            res["verdict"].append(f"ورود معتبر است: {len(t.rows):,} ردیف، {len(t.columns)} ستون" + ("، با ستون نقطه‌ی geom" if t.geometry else ""))
        elif role == "ingest":
            from . import pkgtest

            res["verdict"].append(f"دریافت معتبر است: {pkgtest._check_ingest(spec, out):,} ردیف مطابق فیلدهای {spec.table}")
        elif role == "export":
            name, body, ctype = pluginio.normalize_export(out, spec.format)
            res["verdict"].append(f"خروجی معتبر است: {name} ({len(body):,} بایت، {ctype})")
        else:
            res["verdict"].append("اجرا موفق بود (قالب خروجی را بلوک صفحه‌ی مصرف‌کننده‌اش می‌سنجد: {columns, rows}).")
    except pluginio.PluginIOError as exc:
        res["error"] = f"خروجی handler معتبر نیست: {exc}"
        return res
    res["ok"] = True
    return res


def run_tests(d) -> dict:
    """آزمون‌های پیش‌نویس را در runner اجرا می‌کند: {ok, error, results:[{handler, case, ok, message}]}. چیزی نوشته نمی‌شود."""
    from . import pkgtest

    res = {"ok": False, "error": "", "results": []}
    files = files_of(d)
    try:
        manifest = pkg._manifest(files)
        code = pkg._code(manifest, files)
        tests = pkg._tests(files, code)
        pages = pkg._pages(manifest, files, set(code))
        res["results"] = pkgtest.run_all(code, tests, pkgtest.roles_of(pages))
    except (pkg.PackageError, pkgtest.TestSpecError, ValueError) as exc:
        res["error"] = str(exc)
        return res
    res["ok"] = bool(res["results"]) and all(r["ok"] for r in res["results"])
    return res
