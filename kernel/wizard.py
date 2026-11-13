"""ویزارد ساخت پلاگین (docs/adr/0008، مرحله‌ی ۳): مشخصات **ساخت‌یافته** ← صفحه‌های TOML کیت صفحه.

مدیر جدول، ستون و بلوک را از کاشی و فرم انتخاب می‌کند؛ این ماژول از روی آن‌ها صفحه‌ی TOML می‌سازد و با `pagekit.parse_page`
اعتبارسنجی می‌کند، پس هر چیزی که ویزارد می‌سازد از همان بررسی بسته‌ی دستی (صفحه، SQL فقط‌خواندنی، فرم، ingest، جدول) می‌گذرد.
- **SQL را هسته می‌سازد:** نام جدول و ستون فقط از فهرست اعلام‌شده‌ی ویزارد می‌آید (و با الگوی سخت‌گیر اعتبارسنجی می‌شود)،
  عدد از `int` می‌گذرد؛ هیچ متن آزاد مدیر وارد SQL نمی‌شود، مگر بلوک «SQL پیشرفته» که همان قواعد SQL فقط‌خواندنی کیت را دارد.
- بدون وابستگی به جنگو؛ خروجی `compile_pages` دیکشنری `{کلید صفحه: متن TOML}` است (همان قالب `PluginDraft.pages`).
"""
from __future__ import annotations

import json
import re
import tomllib
from typing import Any

from . import pagekit

ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,40}$")
PARAM_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DISPLAY = ("kpi", "table", "bars", "map", "text", "sql", "handler")
ACTIONS = ("form", "ingest", "records")
FILE_ACTIONS = ("import", "export")
EXTRA = ("report", "source")  # گزارش PDF و واکشی دوره‌ای از API بیرونی (ADR-0009)
KINDS = DISPLAY + ACTIONS + FILE_ACTIONS + EXTRA
HANDLER_DISPLAY = ("table", "kpi", "bars", "map")
EXPORT_FORMATS = ("csv", "json", "txt", "geojson")
AGGS = {"count": "count(*)", "sum": "sum({c})", "avg": "avg({c})", "min": "min({c})", "max": "max({c})"}
NUMERIC = ("integer", "bigint", "double")
MAX_PAGES, MAX_BLOCKS = 6, 12
FIELD_KIND = {"text": "text", "integer": "int", "bigint": "int", "double": "number", "boolean": "bool", "date": "date"}
GEOM_TYPES = ("point", "line", "polygon", "multipolygon")
MAX_PARAMS = 6
PARAM_BIND_KINDS = ("choice", "text")


class WizardError(ValueError):
    """پیام فارسی کوتاه برای مدیر."""


# ---------------------------------------------------------------------- TOML
def _key(k: str) -> str:
    return k if re.fullmatch(r"[A-Za-z0-9_-]+", k) else json.dumps(k, ensure_ascii=False)


def _val(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)  # رشته‌ی JSON، رشته‌ی پایه‌ی TOML هم هست
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_val(x) for x in v) + "]"
    if isinstance(v, dict):
        return "{ " + ", ".join(f"{_key(k)} = {_val(x)}" for k, x in v.items() if x is not None) + " }"
    raise WizardError(f"مقدار پشتیبانی‌نشده در TOML: {type(v).__name__}")


def toml_dumps(page: dict) -> str:
    """صفحه‌ی کیت (dict) ← متن TOML؛ لیست‌های دیکشنری درون‌خطی‌اند (همان قالب مستندات)."""
    scalars = {k: v for k, v in page.items() if not (isinstance(v, list) and v and isinstance(v[0], dict))}
    lines = [f"{_key(k)} = {_val(v)}" for k, v in scalars.items() if v is not None]
    for k, items in page.items():
        if k in scalars:
            continue
        for it in items:
            head = {a: b for a, b in it.items() if not (isinstance(b, list) and b and isinstance(b[0], dict))}
            lines += ["", f"[[{k}]]"] + [f"{_key(a)} = {_val(b)}" for a, b in head.items() if b is not None]
            for a, b in it.items():
                if a not in head:
                    lines.append(f"{_key(a)} = [")
                    lines += [f"  {_val(x)}," for x in b]
                    lines.append("]")
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------- اعتبارسنجی مشخصات
def table_map(spec: dict) -> dict[str, dict]:
    return {t["name"]: t for t in spec.get("tables") or []}


def columns_of(t: dict) -> dict[str, dict]:
    return {c["name"]: c for c in t["columns"]}


def validate_tables(plugin_id: str, tables: list) -> None:
    """هر جدول با همان قاعده‌ی `[[tables]]` کیت سنجیده می‌شود (پیشوند id پلاگین، نوع‌های مجاز، ستون یکتا)."""
    if not ID_RE.fullmatch(plugin_id or ""):
        raise WizardError("شناسه‌ی پلاگین نامعتبر است (حروف کوچک لاتین، رقم و _؛ با حرف شروع شود).")
    seen = set()
    for t in tables:
        try:
            pagekit.parse_table(plugin_id, t)
        except pagekit.SpecError as exc:
            raise WizardError(str(exc)) from exc
        if t["name"] in seen:
            raise WizardError(f"جدول «{t['name']}» تکراری است.")
        seen.add(t["name"])
    if len(tables) > pagekit.MAX_TABLES:
        raise WizardError(f"حداکثر {pagekit.MAX_TABLES} جدول.")


def _need_table(spec: dict, b: dict) -> dict:
    t = table_map(spec).get(b.get("table", ""))
    if t is None:
        raise WizardError("جدولِ این بلوک انتخاب نشده یا در مرحله‌ی «داده» نیست.")
    return t


def _need_col(t: dict, name: str, *, what: str, types: tuple | None = None) -> dict:
    c = columns_of(t).get(name)
    if c is None:
        raise WizardError(f"ستون «{what}» در جدول «{t['name']}» نیست.")
    if types and c["type"] not in types:
        raise WizardError(f"ستون «{name}» باید از نوع {'، '.join(types)} باشد.")
    return c


def q(name: str) -> str:
    """شناسه‌ی SQL با نقل‌قول؛ فقط نام‌های اعتبارسنجی‌شده."""
    if not IDENT_RE.fullmatch(name):
        raise WizardError(f"نام «{name}» نامعتبر است.")
    return f'"{name}"'


def _params_of(page: dict | None) -> dict[str, dict]:
    return {p["name"]: p for p in (page or {}).get("params") or []}


def _where(b: dict, t: dict, page: dict | None) -> str:
    """شرط‌های بلوک: بازه‌ی زمانی ثابت یا وابسته به فیلتر صفحه (`since_param`)، و فیلترهای برابری (`where`: [{param, col}]).
    مقدار فیلتر همیشه با %(نام)s bind می‌شود؛ نام ستون فقط از جدول اعلام‌شده می‌آید."""
    parts: list[str] = []
    col, mins, sp = b.get("since_col") or "", b.get("since_minutes"), b.get("since_param") or ""
    if col:
        _need_col(t, col, what="زمان", types=("timestamptz", "date"))
        if sp:
            p = _params_of(page).get(sp)
            if p is None or p["kind"] != "choice" or not all(str(c[0]).isdigit() for c in p.get("choices") or []):
                raise WizardError("فیلتر بازه‌ی زمانی باید یکی از فیلترهای صفحه از نوع «انتخابی» با گزینه‌های عددی (دقیقه) باشد.")
            parts.append(f"{q(col)} > now() - make_interval(mins => %({sp})s::int)")
        else:
            try:
                n = int(mins)
            except (TypeError, ValueError):
                raise WizardError("بازه‌ی زمانی (دقیقه) عدد است.") from None
            if not 1 <= n <= 525600:
                raise WizardError("بازه‌ی زمانی بین ۱ دقیقه و یک سال باشد.")
            parts.append(f"{q(col)} > now() - interval '{n} minutes'")
    for w in b.get("where") or []:
        pname, wcol = (w or {}).get("param", ""), (w or {}).get("col", "")
        p = _params_of(page).get(pname)
        if p is None or p["kind"] not in PARAM_BIND_KINDS or not PARAM_NAME_RE.fullmatch(pname):
            raise WizardError(f"فیلتر «{pname}» در صفحه نیست (باید «متن» یا «انتخابی» باشد).")
        _need_col(t, wcol, what="ستون فیلتر")
        parts.append(f"({q(wcol)}::text = %({pname})s or %({pname})s = '')")
    return (" where " + " and ".join(parts)) if parts else ""


def block_sql(spec: dict, b: dict, page: dict | None = None) -> tuple[str, dict]:
    """بلوک نمایشی ← (SQL فقط‌خواندنی، فیلدهای اضافه‌ی بلوک مثل unit/columns). WizardError با پیام فارسی."""
    kind = b["kind"]
    if kind == "sql":
        return str(b.get("sql", "")).strip(), {}
    t = _need_table(spec, b)
    rel = q(t["name"])
    if kind == "kpi":
        agg = b.get("agg", "count")
        if agg not in AGGS:
            raise WizardError("تابع شمارنده نامعتبر است.")
        expr = AGGS[agg]
        if agg != "count":
            _need_col(t, b.get("column", ""), what="مقدار", types=NUMERIC)
            expr = expr.format(c=q(b["column"]))
        if agg == "count" and b.get("distinct"):
            _need_col(t, b["distinct"], what="یکتا")
            expr = f"count(distinct {q(b['distinct'])})"
        return f"select {expr} from {rel}{_where(b, t, page)}", {"unit": str(b.get("unit", ""))[:30]}
    if kind == "table":
        cols = b.get("columns") or [c["name"] for c in t["columns"]][:6]
        for c in cols:
            _need_col(t, c, what=c)
        order = b.get("order_by") or "id"
        if order != "id":
            _need_col(t, order, what="مرتب‌سازی")
        limit = int(b.get("limit") or 20)
        if not 1 <= limit <= 200:
            raise WizardError("تعداد ردیف بین ۱ و ۲۰۰ باشد.")
        direction = "desc" if b.get("desc", True) else "asc"
        return (f"select {', '.join(q(c) for c in cols)} from {rel}{_where(b, t, page)} order by {q(order)} {direction} limit {limit}",
                {"columns": [[c, c] for c in cols]})
    if kind == "bars":
        _need_col(t, b.get("label", ""), what="برچسب")
        agg = b.get("agg", "count")
        if agg not in AGGS:
            raise WizardError("تابع نمودار نامعتبر است.")
        val = AGGS[agg]
        if agg != "count":
            _need_col(t, b.get("column", ""), what="مقدار", types=NUMERIC)
            val = val.format(c=q(b["column"]))
        lab = q(b["label"])
        return f"select {lab}::text as label, {val} as value from {rel}{_where(b, t, page)} group by {lab} order by value desc limit 20", {}
    if kind == "map":
        props = [c for c in (b.get("props") or []) if c]
        for c in props:
            _need_col(t, c, what=c)
        if b.get("point"):
            _need_col(t, b["point"], what="نقطه", types=("point",))
            geom = q(b["point"])
        else:
            _need_col(t, b.get("lat", ""), what="عرض", types=("double",))
            _need_col(t, b.get("lon", ""), what="طول", types=("double",))
            geom = f"st_setsrid(st_makepoint({q(b['lon'])}, {q(b['lat'])}), 4326)"
        sel = ", ".join(q(c) for c in props)
        sel = (sel + ", " if sel else "") + f"{geom} as geom"
        if b.get("latest_by"):
            _need_col(t, b["latest_by"], what="شناسه‌ی دستگاه")
            _need_col(t, b.get("time_col", ""), what="زمان", types=("timestamptz", "date"))
            order = f"{q(b['latest_by'])}, {q(b['time_col'])} desc"
            return f"select distinct on ({q(b['latest_by'])}) {sel} from {rel}{_where(b, t, page)} order by {order}", {}
        return f"select {sel} from {rel}{_where(b, t, page)} limit 2000", {}
    raise WizardError("نوع بلوک نامعتبر است.")


def _choices(raw) -> list[list[str]]:
    out = []
    for c in raw or []:
        if isinstance(c, (list, tuple)) and len(c) == 2:
            out.append([str(c[0]).strip()[:60], str(c[1]).strip()[:60]])
        elif isinstance(c, str) and c.strip():
            out.append([c.strip()[:60], c.strip()[:60]])
    return [c for c in out if c[0]]


def _field_for(c: dict) -> dict:
    if c["type"] in GEOM_TYPES:
        return {"name": c["name"], "kind": "geometry", "geom": c["type"], "label": c.get("label") or c["name"], "required": bool(c.get("required"))}
    kind = FIELD_KIND.get(c["type"])
    if kind is None:
        raise WizardError(f"ستون «{c['name']}» از نوع {c['type']} در فرم/دریافت داده پشتیبانی نمی‌شود.")
    f = {"name": c["name"], "kind": kind, "label": c.get("label") or c["name"], "required": bool(c.get("required"))}
    ch = _choices(c.get("choices"))
    if c["type"] == "text" and ch:
        f["kind"], f["choices"] = "choice", ch
        return f
    for k in ("min", "max"):  # کران ستون (مثلاً عرض/طول جغرافیایی) در فرم و دریافت داده اعمال می‌شود
        if isinstance(c.get(k), (int, float)) and not isinstance(c.get(k), bool):
            f[k] = c[k]
    if kind == "text":
        f["max"] = 200
    return f


def _action_columns(t: dict, b: dict) -> list[dict]:
    geom_ok = b.get("kind") in ("form", "records")
    names = b.get("fields") or [c["name"] for c in t["columns"] if not c.get("auto_now") and (c["type"] in FIELD_KIND or geom_ok and c["type"] in GEOM_TYPES)]
    if not names:
        raise WizardError("دست‌کم یک ستونِ قابل‌نوشتن لازم است.")
    out = []
    for n in names:
        c = _need_col(t, n, what=n)
        if c.get("auto_now"):
            raise WizardError(f"ستون «{n}» را پایگاه خودکار پر می‌کند.")
        out.append(_field_for(c))
    return out


def handler_for(spec: dict, name: str, role: str) -> str:
    """handler موجود در مرحله‌ی «کد» با نقش درست (block|importer|exporter|ingest|alert)؛ نام را برمی‌گرداند یا WizardError."""
    labels = {"block": "بلوک صفحه", "importer": "ورود فایل", "exporter": "خروجی فایل", "ingest": "تبدیل داده‌ی دریافتی", "alert": "هشدار دوره‌ای"}
    h = (spec.get("code") or {}).get(name or "")
    if h is None:
        raise WizardError(f"handler «{name}» در مرحله‌ی «کد» نیست.")
    if h.get("role") != role:
        raise WizardError(f"handler «{name}» از نوع «{labels.get(h.get('role'), '؟')}» است، نه «{labels[role]}».")
    return name


def _exts(raw) -> list[str]:
    out = [e.strip().lower() for e in (raw if isinstance(raw, list) else str(raw or "").replace("،", ",").split(",")) if str(e).strip()]
    out = [e if e.startswith(".") else "." + e for e in out]
    for e in out:
        if not re.fullmatch(r"\.[a-z0-9]{1,8}", e):
            raise WizardError(f"پسوند «{e}» نامعتبر است (مثل .csv).")
    if len(out) > 8:
        raise WizardError("حداکثر ۸ پسوند.")
    return out


def _records_item(spec: dict, b: dict, key: str) -> dict:
    t = _need_table(spec, b)
    flds = _action_columns(t, b)
    plain = [f["name"] for f in flds if f["kind"] != "geometry"]
    cols = [c for c in (b.get("columns") or plain[:4]) if c in plain]
    if not cols:
        raise WizardError("دست‌کم یک ستون غیرمکانی برای فهرست نمایش بدهید.")
    return {"key": key, "title": b.get("title") or "ویرایش ردیف‌ها", "table": t["name"], "fields": flds, "columns": cols[:6],
            "can_delete": b.get("can_delete", True) is not False, "limit": min(max(int(b.get("limit") or 50), 1), 100), "hint": str(b.get("hint", ""))[:240]}


def _source_item(spec: dict, b: dict, key: str) -> dict:
    t = _need_table(spec, b)
    flds = []
    for m in b.get("map") or []:
        if not (m or {}).get("column"):
            continue  # سطر خالی (تازه‌افزوده) نادیده گرفته می‌شود
        c = _need_col(t, (m or {}).get("column", ""), what="ستون مقصد")
        f = _field_for(c)
        if f["kind"] == "geometry":
            raise WizardError("ستون مکانی برای منبع بیرونی پشتیبانی نمی‌شود.")
        path = str((m or {}).get("path") or c["name"]).strip()
        flds.append({**f, "path": path})
    if not flds:
        raise WizardError("دست‌کم یک نگاشت «مسیر در پاسخ ← ستون» لازم است.")
    q = b.get("query") or []
    qd = dict(q) if isinstance(q, dict) else {str(k): str(v) for k, v in (x for x in q if isinstance(x, (list, tuple)) and len(x) == 2) if str(k).strip()}
    item = {"key": key, "title": b.get("title") or "واکشی از API", "url": str(b.get("url", "")).strip(), "table": t["name"], "fields": flds,
            "layout": b.get("layout") or "rows", "every_minutes": int(b.get("every_minutes") or 180), "since_days": int(b.get("since_days") or 2)}
    for k in ("rows_path", "cursor", "hint", "secret_header", "secret_param"):
        if str(b.get(k) or "").strip():
            item[k] = str(b[k]).strip()
    if qd:
        item["query"] = qd
    inputs = [i for i in b.get("inputs") or [] if isinstance(i, dict) and str(i.get("name", "")).strip()]
    if inputs:
        item["inputs"] = [{k: v for k, v in i.items() if v not in (None, "")} for i in inputs]
    return item


def _report_item(page: dict | None, b: dict, key: str) -> dict:
    ids = [i for i in b.get("blocks") or [] if isinstance(i, str)]
    out = {"key": key, "title": b.get("title") or "گزارش", "orientation": "landscape" if b.get("landscape") else "portrait",
           "button": str(b.get("button") or "گزارش PDF")[:30]}
    if str(b.get("subtitle") or "").strip():
        out["subtitle"] = str(b["subtitle"]).strip()[:240]
    if page is not None:
        disp = [x["id"] for x in page.get("blocks") or [] if x.get("kind") in DISPLAY + ("handler",) and x.get("id")]
        for i in ids:
            if i not in disp:
                raise WizardError("بلوک انتخاب‌شده برای گزارش در این صفحه نیست یا نمایشی نیست.")
        out["blocks"] = [disp.index(i) + 1 for i in ids]
    return out


def _check_params(page: dict | None) -> None:
    ps = (page or {}).get("params") or []
    if len(ps) > MAX_PARAMS:
        raise WizardError(f"حداکثر {MAX_PARAMS} فیلتر در هر صفحه.")
    names = set()
    for p in ps:
        if not PARAM_NAME_RE.fullmatch(str(p.get("name", ""))) or p["name"] in names:
            raise WizardError("نام فیلتر نامعتبر یا تکراری است.")
        names.add(p["name"])
        try:
            pagekit.parse_param(p)
        except pagekit.SpecError as exc:
            raise WizardError(f"فیلتر «{p.get('label') or p['name']}»: {exc}") from exc


def check_block(spec: dict, b: dict, page: dict | None = None) -> None:
    """یک بلوک را تنها (بدون نیاز به کامل‌بودن صفحه) می‌سنجد؛ WizardError با پیام فارسی."""
    kind = b.get("kind")
    if kind == "text":
        return
    _check_params(page)
    if kind == "handler":
        handler_for(spec, b.get("handler", ""), "block")
        if b.get("display") not in HANDLER_DISPLAY:
            raise WizardError("نوع نمایش خروجی کد را انتخاب کنید.")
        return
    if kind == "import":
        handler_for(spec, b.get("handler", ""), "importer")
        _exts(b.get("extensions"))
        return
    if kind == "export":
        handler_for(spec, b.get("handler", ""), "exporter")
        if b.get("format", "csv") not in EXPORT_FORMATS:
            raise WizardError("قالب خروجی نامعتبر است.")
        return
    if kind == "records":
        try:
            pagekit.parse_record(_records_item(spec, b, "rec1"))
        except pagekit.SpecError as exc:
            raise WizardError(str(exc)) from exc
        return
    if kind in ACTIONS:
        if kind == "ingest" and b.get("handler"):
            handler_for(spec, b["handler"], "ingest")
        _action_columns(_need_table(spec, b), b)
        return
    if kind == "source":
        try:
            pagekit.parse_source(_source_item(spec, b, "src1"))
        except pagekit.SpecError as exc:
            raise WizardError(str(exc)) from exc
        return
    if kind == "report":
        _report_item(page, b, "rep1")
        return
    sql, _extra = block_sql(spec, b, page)
    if kind == "sql" and not sql:
        raise WizardError("SQL را بنویسید.")


# ---------------------------------------------------------------------- ساخت صفحه
def build_page(spec: dict, plugin_id: str, page: dict) -> dict:
    """یک صفحه‌ی مشخصات ساخت‌یافته ← dict مشخصات کیت صفحه (قابل `pagekit.parse_page`)."""
    tmap = table_map(spec)
    out: dict[str, Any] = {"key": page["key"], "title": page["title"], "subtitle": page.get("subtitle", ""),
                           "icon": page.get("icon", "chart"), "group": page.get("group", "data"), "need": page.get("need", "viewer"),
                           "order": int(page.get("order", 100))}
    if int(page.get("refresh", 0) or 0):
        out["refresh"] = int(page["refresh"])
    _check_params(page)
    if page.get("params"):
        out["params"] = [{k: v for k, v in p.items() if v not in (None, "")} for p in page["params"]]
    blocks, forms, ingests, imports, exports, used = [], [], [], [], [], []
    records, sources, reports, emitted = [], [], [], []
    for b in page.get("blocks") or []:
        kind = b["kind"]
        if kind == "records":
            item = _records_item(spec, b, f"rec{len(records) + 1}")
            used.append(item["table"])
            records.append(item)
            continue
        if kind == "source":
            item = _source_item(spec, b, f"src{len(sources) + 1}")
            used.append(item["table"])
            sources.append(item)
            continue
        if kind == "report":
            reports.append((b, f"rep{len(reports) + 1}"))
            continue
        if kind == "import":
            imports.append({"key": f"imp{len(imports) + 1}", "title": b.get("title") or "ورود فایل", "handler": handler_for(spec, b.get("handler", ""), "importer"),
                            "extensions": _exts(b.get("extensions"))})
            continue
        if kind == "export":
            exports.append({"key": f"exp{len(exports) + 1}", "title": b.get("title") or "دریافت خروجی", "handler": handler_for(spec, b.get("handler", ""), "exporter"),
                            "format": b.get("format") if b.get("format") in EXPORT_FORMATS else "csv"})
            continue
        if kind in ACTIONS:
            t = _need_table(spec, b)
            used.append(t["name"])
            flds = _action_columns(t, b)
            key = f"{kind}{len(forms) + len(ingests) + 1}"
            if kind == "form":
                form = {"key": key, "title": b.get("title") or "ثبت", "table": t["name"], "fields": flds}
                for k, lim in (("submit", 30), ("hint", 240), ("success", 120)):
                    if str(b.get(k) or "").strip():
                        form[k] = str(b[k]).strip()[:lim]
                forms.append(form)
            else:
                ing = {"key": key, "title": b.get("title") or "دریافت داده‌ی دستگاه", "table": t["name"], "fields": flds,
                       "max_rows": int(b.get("max_rows") or 100), "rate": int(b.get("rate") or 60)}
                if b.get("handler"):
                    ing["handler"] = handler_for(spec, b["handler"], "ingest")
                ingests.append(ing)
            continue
        if kind == "handler":
            disp = b.get("display")
            if disp not in HANDLER_DISPLAY:
                raise WizardError("نوع نمایش خروجی کد را انتخاب کنید.")
            hname = handler_for(spec, b.get("handler", ""), "block")
            used += [t for t in (spec["code"][hname].get("tables") or []) if t in tmap]  # جدولی که کد می‌خواند باید ساخته شود
            item = {"kind": disp, "title": b.get("title", ""), "handler": hname}
            if disp == "kpi" and b.get("unit"):
                item["unit"] = str(b["unit"])[:30]
            if b.get("width") in ("full", "half", "third"):
                item["width"] = b["width"]
            blocks.append(item)
            emitted.append(b.get("id"))
            continue
        item: dict[str, Any] = {"kind": kind, "title": b.get("title", "")}
        if kind == "text":
            item["text"] = str(b.get("text", ""))
        else:
            sql, extra = block_sql(spec, b, page)
            item["sql"] = sql
            item.update({k: v for k, v in extra.items() if v})
            display = b.get("display") if kind == "sql" else kind
            item["kind"] = display if display in ("kpi", "table", "bars", "map") else "table"
            if b.get("table"):
                used.append(b["table"])
        if b.get("width") in ("full", "half", "third"):
            item["width"] = b["width"]
        blocks.append(item)
        emitted.append(b.get("id"))
    if not blocks:
        raise WizardError(f"صفحه‌ی «{page['title']}» دست‌کم یک بلوک نمایشی (شمارنده، جدول، نمودار، نقشه یا متن) لازم دارد.")
    out["blocks"] = blocks
    if forms:
        out["forms"] = forms
    if ingests:
        out["ingest"] = ingests
    if imports:
        out["imports"] = imports
    if exports:
        out["exports"] = exports
    if records:
        out["records"] = records
    if sources:
        out["sources"] = sources
    if reports:
        shown = {"blocks": [{"id": i, "kind": "kpi"} for i in emitted if i]}
        out["reports"] = [_report_item(shown, b, key) for b, key in reports]
    if used:
        out["tables"] = [tmap[n] for n in dict.fromkeys(used)]
    if (forms or ingests or imports or records or sources) and out["need"] == "viewer":
        out["need"] = "editor"
    return out


def compile_pages(plugin_id: str, spec: dict) -> dict[str, str]:
    """همه‌ی صفحه‌ها ← {کلید: TOML}، با اعتبارسنجی کامل کیت. WizardError با نام صفحه."""
    validate_tables(plugin_id, spec.get("tables") or [])
    pages = spec.get("pages") or []
    if len(pages) > MAX_PAGES:
        raise WizardError(f"حداکثر {MAX_PAGES} صفحه.")
    out, keys = {}, set()
    for p in pages:
        if len(p.get("blocks") or []) > MAX_BLOCKS:
            raise WizardError(f"حداکثر {MAX_BLOCKS} بلوک در هر صفحه.")
        if p["key"] in keys:
            raise WizardError("کلید صفحه تکراری است.")
        keys.add(p["key"])
        try:
            built = build_page(spec, plugin_id, p)
            text = toml_dumps(built)
            pagekit.parse_page(plugin_id, tomllib.loads(text))  # همان بررسی بسته
        except pagekit.SpecError as exc:
            raise WizardError(f"صفحه‌ی «{p.get('title', p['key'])}»: {exc}") from exc
        out[p["key"]] = text
    return out


def next_page_key(spec: dict) -> str:
    used = {p["key"] for p in spec.get("pages") or []}
    i = 1
    while f"p{i}" in used:
        i += 1
    return f"p{i}"
