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
IDENT_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
DISPLAY = ("kpi", "table", "bars", "map", "text", "sql")
ACTIONS = ("form", "ingest")
KINDS = DISPLAY + ACTIONS
AGGS = {"count": "count(*)", "sum": "sum({c})", "avg": "avg({c})", "min": "min({c})", "max": "max({c})"}
NUMERIC = ("integer", "bigint", "double")
MAX_PAGES, MAX_BLOCKS = 6, 12
FIELD_KIND = {"text": "text", "integer": "int", "bigint": "int", "double": "number", "boolean": "bool", "date": "date"}


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


def _since(b: dict, t: dict) -> str:
    col, mins = b.get("since_col") or "", b.get("since_minutes")
    if not col:
        return ""
    _need_col(t, col, what="زمان", types=("timestamptz", "date"))
    try:
        n = int(mins)
    except (TypeError, ValueError):
        raise WizardError("بازه‌ی زمانی (دقیقه) عدد است.") from None
    if not 1 <= n <= 525600:
        raise WizardError("بازه‌ی زمانی بین ۱ دقیقه و یک سال باشد.")
    return f" where {q(col)} > now() - interval '{n} minutes'"


def block_sql(spec: dict, b: dict) -> tuple[str, dict]:
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
        return f"select {expr} from {rel}{_since(b, t)}", {"unit": str(b.get("unit", ""))[:30]}
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
        return (f"select {', '.join(q(c) for c in cols)} from {rel}{_since(b, t)} order by {q(order)} {direction} limit {limit}",
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
        return f"select {lab}::text as label, {val} as value from {rel}{_since(b, t)} group by {lab} order by value desc limit 20", {}
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
            return f"select distinct on ({q(b['latest_by'])}) {sel} from {rel}{_since(b, t)} order by {order}", {}
        return f"select {sel} from {rel}{_since(b, t)} limit 2000", {}
    raise WizardError("نوع بلوک نامعتبر است.")


def _field_for(c: dict) -> dict:
    kind = FIELD_KIND.get(c["type"])
    if kind is None:
        raise WizardError(f"ستون «{c['name']}» از نوع {c['type']} در فرم/دریافت داده پشتیبانی نمی‌شود.")
    f = {"name": c["name"], "kind": kind, "label": c.get("label") or c["name"], "required": bool(c.get("required"))}
    if kind == "text":
        f["max"] = 200
    return f


def _action_columns(t: dict, b: dict) -> list[dict]:
    names = b.get("fields") or [c["name"] for c in t["columns"] if not c.get("auto_now") and c["type"] in FIELD_KIND]
    if not names:
        raise WizardError("دست‌کم یک ستونِ قابل‌نوشتن لازم است.")
    out = []
    for n in names:
        c = _need_col(t, n, what=n)
        if c.get("auto_now"):
            raise WizardError(f"ستون «{n}» را پایگاه خودکار پر می‌کند.")
        out.append(_field_for(c))
    return out


def check_block(spec: dict, b: dict) -> None:
    """یک بلوک را تنها (بدون نیاز به کامل‌بودن صفحه) می‌سنجد؛ WizardError با پیام فارسی."""
    kind = b.get("kind")
    if kind == "text":
        return
    if kind in ACTIONS:
        _action_columns(_need_table(spec, b), b)
        return
    sql, _extra = block_sql(spec, b)
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
    blocks, forms, ingests, used = [], [], [], []
    for b in page.get("blocks") or []:
        kind = b["kind"]
        if kind in ACTIONS:
            t = _need_table(spec, b)
            used.append(t["name"])
            flds = _action_columns(t, b)
            key = f"{kind}{len(forms) + len(ingests) + 1}"
            if kind == "form":
                forms.append({"key": key, "title": b.get("title") or "ثبت", "table": t["name"], "fields": flds})
            else:
                ingests.append({"key": key, "title": b.get("title") or "دریافت داده‌ی دستگاه", "table": t["name"], "fields": flds,
                                "max_rows": int(b.get("max_rows") or 100), "rate": int(b.get("rate") or 60)})
            continue
        item: dict[str, Any] = {"kind": kind, "title": b.get("title", "")}
        if kind == "text":
            item["text"] = str(b.get("text", ""))
        else:
            sql, extra = block_sql(spec, b)
            item["sql"] = sql
            item.update({k: v for k, v in extra.items() if v})
            display = b.get("display") if kind == "sql" else kind
            item["kind"] = display if display in ("kpi", "table", "bars", "map") else "table"
            if b.get("table"):
                used.append(b["table"])
        if b.get("width") in ("full", "half", "third"):
            item["width"] = b["width"]
        blocks.append(item)
    if not blocks:
        raise WizardError(f"صفحه‌ی «{page['title']}» دست‌کم یک بلوک نمایشی (شمارنده، جدول، نمودار، نقشه یا متن) لازم دارد.")
    out["blocks"] = blocks
    if forms:
        out["forms"] = forms
    if ingests:
        out["ingest"] = ingests
    if used:
        out["tables"] = [tmap[n] for n in dict.fromkeys(used)]
    if (forms or ingests) and out["need"] == "viewer":
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
