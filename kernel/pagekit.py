"""کیت صفحه: پلاگین HTML و CSS نمی‌نویسد؛ صفحه را با «مشخصات» (داده) توصیف می‌کند و هسته آن را با اجزای سیستم طراحی می‌سازد.

یکدستی (راست‌به‌چپ، ۴۰۰ پیکسل، حالت خالی و خطا) به‌طور ساختاری تضمین است، نه با بازبینی.

بلوک‌ها: text، kpi، table، bars، map. منبع داده‌ی هر بلوک یک `SELECT` است که فقط **خواندنی** و با نقش محدود مرورگر روی
پایگاه همان مشتری اجرا می‌شود (تراکنش فقط‌خواندنی، حد زمانی، سقف ردیف، یک دستور). مقدارهای پارامتر همیشه bind می‌شوند
(`%(name)s`)؛ نام جدول فقط از پارامتر نوع `layer` و با `sql.Identifier` (`{name}`) داخل SQL می‌آید.

نویسه‌ی `%` واقعی در SQL را `%%` و `{`/`}` واقعی را `{{`/`}}` بنویسید.
"""
from __future__ import annotations

import json
import re
import string
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from psycopg import sql

from . import nav, tenantdb
from .plugins import registry

POINT = "page.spec"
KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
BLOCKS = ("text", "kpi", "table", "bars", "map")
WIDTHS = ("full", "half", "third")
PARAM_KINDS = ("int", "number", "text", "choice", "layer")
GROUPS = ("data", "share", "manage")
NEEDS = ("viewer", "editor", "owner")
TIMEOUT_S = 8
MAX_SQL = 4000
LIMITS = {"table": 200, "bars": 50, "map": 2000, "kpi": 1}


class SpecError(ValueError):
    """مشخصات صفحه نامعتبر است (پیام فارسی برای گزارش بررسی بسته)."""


@dataclass(frozen=True)
class Param:
    name: str
    kind: str
    label: str
    default: str = ""
    choices: tuple[tuple[str, str], ...] = ()
    min: float | None = None
    max: float | None = None


@dataclass(frozen=True)
class Block:
    kind: str
    title: str = ""
    width: str = "full"
    sql: str = ""
    text: str = ""
    unit: str = ""
    hint: str = ""
    columns: tuple[tuple[str, str], ...] = ()  # (نام ستون، برچسب)


@dataclass(frozen=True)
class Page:
    plugin: str
    key: str
    title: str
    subtitle: str = ""
    icon: str = "chart"
    group: str = "share"
    need: str = "viewer"
    order: int = 100
    refresh: int = 0  # ثانیه؛ ۰ = تازه‌سازی خودکار ندارد
    params: tuple[Param, ...] = ()
    blocks: tuple[Block, ...] = ()


_icon_known = lambda name: True  # noqa: E731  هسته فهرست آیکون‌ها را نمی‌شناسد؛ پلاگین هسته‌ی سایت آن را ثبت می‌کند


def set_icon_checker(fn) -> None:
    global _icon_known
    _icon_known = fn


# ---------------------------------------------------------------------- اعتبارسنجی مشخصات
def _str(d: dict, k: str, *, required=False, limit=200, default="") -> str:
    v = d.get(k, default)
    if v is None:
        v = default
    if not isinstance(v, str):
        raise SpecError(f"«{k}» باید متن باشد.")
    v = v.strip()
    if required and not v:
        raise SpecError(f"«{k}» لازم است.")
    if len(v) > limit:
        raise SpecError(f"«{k}» بیش از {limit} نویسه است.")
    return v


def _sql_fields(text: str) -> set[str]:
    try:
        return {f for _lit, f, _s, _c in string.Formatter().parse(text) if f is not None}
    except ValueError as exc:
        raise SpecError(f"آکولاد در SQL نامعتبر است (آکولاد واقعی را دوبار بنویسید): {exc}") from exc


def _sql_values(text: str) -> set[str]:
    return set(re.findall(r"%\((\w+)\)s", text))


def parse_param(d: dict) -> Param:
    name = _str(d, "name", required=True, limit=31)
    if not PARAM_RE.fullmatch(name):
        raise SpecError(f"نام پارامتر «{name}» نامعتبر است.")
    kind = _str(d, "kind", required=True)
    if kind not in PARAM_KINDS:
        raise SpecError(f"نوع پارامتر «{kind}» شناخته نیست.")
    choices = ()
    if kind == "choice":
        raw = d.get("choices") or []
        if not raw or not all(isinstance(c, (list, tuple)) and len(c) == 2 for c in raw):
            raise SpecError(f"پارامتر انتخابی «{name}» گزینه‌های [مقدار، برچسب] لازم دارد.")
        choices = tuple((str(a), str(b)) for a, b in raw)
    lo, hi = d.get("min"), d.get("max")
    for v in (lo, hi):
        if v is not None and not isinstance(v, (int, float)):
            raise SpecError(f"کران پارامتر «{name}» باید عدد باشد.")
    return Param(name, kind, _str(d, "label", required=True, limit=80), _str(d, "default", limit=100), choices, lo, hi)


def parse_block(d: dict, params: dict[str, Param]) -> Block:
    kind = _str(d, "kind", required=True)
    if kind not in BLOCKS:
        raise SpecError(f"نوع بلوک «{kind}» شناخته نیست (مجاز: {'، '.join(BLOCKS)}).")
    width = _str(d, "width", default="third" if kind == "kpi" else "full")
    if width not in WIDTHS:
        raise SpecError(f"عرض بلوک «{width}» نامعتبر است.")
    text, query = _str(d, "text", limit=4000), _str(d, "sql", limit=MAX_SQL)
    if kind == "text" and not text:
        raise SpecError("بلوک متنی باید «text» داشته باشد.")
    if kind != "text":
        if not query:
            raise SpecError(f"بلوک «{kind}» باید «sql» داشته باشد.")
        if not re.match(r"^\s*(select|with)\b", query, re.I):
            raise SpecError("منبع داده فقط می‌تواند SELECT یا WITH باشد.")
        for f in _sql_fields(query):
            if f not in params or params[f].kind != "layer":
                raise SpecError(f"جای‌نگهدار {{{f}}} فقط برای پارامتر نوع layer مجاز است.")
        missing = _sql_values(query) - set(params)
        if missing:
            raise SpecError(f"پارامتر اعلام‌نشده در SQL: {'، '.join(sorted(missing))}")
        if any(params[v].kind == "layer" for v in _sql_values(query) if v in params):
            raise SpecError("پارامتر layer را با {نام} بیاورید، نه %(نام)s.")
    cols = d.get("columns") or []
    if cols and not all(isinstance(c, (list, tuple)) and len(c) == 2 for c in cols):
        raise SpecError("«columns» فهرست [نام ستون، برچسب] است.")
    return Block(kind, _str(d, "title", limit=100), width, query, text, _str(d, "unit", limit=20),
                 _str(d, "hint", limit=200), tuple((str(a), str(b)) for a, b in cols))


def parse_page(plugin: str, d: dict) -> Page:
    """مشخصات خام (dict از TOML/JSON) ← Page اعتبارسنجی‌شده. خطا = SpecError با پیام فارسی."""
    if not isinstance(d, dict):
        raise SpecError("مشخصات صفحه باید یک شیء باشد.")
    key = _str(d, "key", required=True, limit=31)
    if not KEY_RE.fullmatch(key):
        raise SpecError(f"کلید صفحه «{key}» نامعتبر است (حروف کوچک لاتین، رقم و _).")
    icon = _str(d, "icon", default="chart", limit=40)
    if not _icon_known(icon):
        raise SpecError(f"آیکون «{icon}» در مجموعه‌ی سیستم طراحی نیست.")
    group, need = _str(d, "group", default="share"), _str(d, "need", default="viewer")
    if group not in GROUPS:
        raise SpecError(f"گروه منو «{group}» نامعتبر است (مجاز: {'، '.join(GROUPS)}).")
    if need not in NEEDS:
        raise SpecError(f"سطح دسترسی «{need}» نامعتبر است.")
    refresh = d.get("refresh", 0)
    if not isinstance(refresh, int) or isinstance(refresh, bool) or not (refresh == 0 or 5 <= refresh <= 3600):
        raise SpecError("«refresh» صفر یا بین ۵ تا ۳۶۰۰ ثانیه است.")
    order = d.get("order", 100)
    if not isinstance(order, int) or isinstance(order, bool):
        raise SpecError("«order» باید عدد صحیح باشد.")
    params = [parse_param(p) for p in d.get("params") or []]
    if len({p.name for p in params}) != len(params):
        raise SpecError("نام پارامترها باید یکتا باشد.")
    by_name = {p.name: p for p in params}
    blocks = [parse_block(b, by_name) for b in d.get("blocks") or []]
    if not blocks:
        raise SpecError("صفحه دست‌کم یک بلوک لازم دارد.")
    if len(blocks) > 24:
        raise SpecError("حداکثر ۲۴ بلوک در یک صفحه.")
    return Page(plugin, key, _str(d, "title", required=True, limit=80), _str(d, "subtitle", limit=240), icon, group, need,
                order, refresh, tuple(params), tuple(blocks))


# ---------------------------------------------------------------------- ثبت
def register(plugin: str, page: Page) -> None:
    """صفحه را در رجیستری و منوی ریل پایگاه ثبت می‌کند (مدیریت دسترسی را موتور مجوز انجام می‌دهد)."""
    registry.add(POINT, f"{plugin}:{page.key}", page, plugin=plugin, order=page.order, replace=True)
    nav.ws_section(page.group, page.title, "kernel:page", page.icon, page.need, plugin=plugin, order=page.order,
                   views=("kernel:page",), extra=(plugin, page.key))


def unregister_plugin(plugin: str) -> None:
    """همه‌ی صفحه‌های یک پلاگین را برمی‌دارد (با remove_plugin رجیستری)."""
    registry.remove_plugin(plugin)


def get(plugin: str, key: str) -> Page | None:
    return registry.get(POINT, f"{plugin}:{key}")


def pages() -> list[Page]:
    return registry.values(POINT)


# ---------------------------------------------------------------------- مقدار پارامترها
def read_values(page: Page, query, layers: dict[str, str]) -> tuple[dict, list[str]]:
    """مقدارهای پارامتر از نشانی (GET) با اعتبارسنجی؛ مقدار نامعتبر = پیش‌فرض + پیام. layers: «schema.table» های مجاز."""
    values, errors = {}, []
    for p in page.params:
        raw = (query.get(p.name) if query is not None else None)
        raw = p.default if raw in (None, "") else raw
        try:
            values[p.name] = _convert(p, raw, layers)
        except (ValueError, KeyError):
            errors.append(f"مقدار «{p.label}» نامعتبر بود؛ مقدار پیش‌فرض به‌کار رفت.")
            try:
                values[p.name] = _convert(p, p.default, layers)
            except (ValueError, KeyError):
                values[p.name] = None
    return values, errors


def _convert(p: Param, raw, layers):
    if p.kind == "text":
        return str(raw)[:100]
    if p.kind == "choice":
        if str(raw) not in {c[0] for c in p.choices}:
            raise ValueError
        return str(raw)
    if p.kind == "layer":
        if str(raw) not in layers:
            raise ValueError
        return str(raw)
    num = int(raw) if p.kind == "int" else float(raw)
    if (p.min is not None and num < p.min) or (p.max is not None and num > p.max):
        raise ValueError
    return num


# ---------------------------------------------------------------------- اجرای منبع داده
def _compose(template: str, layer_values: dict[str, str]) -> sql.Composable:
    parts: list[sql.Composable] = []
    for literal, name, _spec, _conv in string.Formatter().parse(template):
        if literal:
            parts.append(sql.SQL(literal))
        if name is not None:
            schema, _, table = layer_values[name].partition(".")
            parts.append(sql.Identifier(schema, table))
    return sql.Composed(parts)


def run_sql(ws, block: Block, page: Page, values: dict, *, kind: str | None = None) -> tuple[list[str], list[tuple]]:
    """SELECT بلوک را فقط‌خواندنی اجرا می‌کند و (نام ستون‌ها، ردیف‌ها) برمی‌گرداند."""
    layer_values = {p.name: values[p.name] for p in page.params if p.kind == "layer" and values.get(p.name)}
    if any(f not in layer_values for f in _sql_fields(block.sql)):
        raise SpecError("لایه‌ی انتخاب‌شده برای این بلوک در دسترس نیست.")
    inner = _compose(block.sql, layer_values)
    limit = LIMITS.get(kind or block.kind, 200)
    if (kind or block.kind) == "map":
        query = sql.SQL(
            "SELECT ST_AsGeoJSON(CASE WHEN ST_SRID(q.geom::geometry) IN (0, 4326) THEN q.geom::geometry "
            "ELSE ST_Transform(q.geom::geometry, 4326) END)::text AS __geom, to_jsonb(q) - 'geom' AS __props "
            "FROM ({}) AS q WHERE q.geom IS NOT NULL LIMIT %(__limit)s").format(inner)
    else:
        query = sql.SQL("SELECT * FROM ({}) AS q LIMIT %(__limit)s").format(inner)
    args = {p.name: values.get(p.name) for p in page.params if p.kind != "layer"}
    args["__limit"] = limit
    with tenantdb.connect(ws) as conn:  # نقش محدود مرورگر + تراکنش فقط‌خواندنی
        conn.execute(sql.SQL("SET LOCAL statement_timeout = {}").format(sql.Literal(f"{TIMEOUT_S}s")))
        cur = conn.execute(query, args, prepare=True)  # پروتکل گسترده: فقط یک دستور
        cols = [d.name for d in cur.description]
        return cols, cur.fetchall()


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, bool):
        return "بله" if v else "خیر"
    if isinstance(v, (int, Decimal)) or (isinstance(v, float) and v.is_integer()):
        return f"{int(v):,}"
    if isinstance(v, float):
        return f"{v:,.2f}"
    if isinstance(v, (datetime, date)):
        return v.strftime("%Y-%m-%d %H:%M") if isinstance(v, datetime) else v.isoformat()
    s = str(v)
    return s if len(s) <= 200 else s[:200] + "…"


def render_block(ws, page: Page, block: Block, values: dict) -> dict:
    """مدل نمایش یک بلوک برای قالب. خطای داده فقط همین بلوک را به پیام کوتاه تبدیل می‌کند."""
    out = {"kind": block.kind, "title": block.title, "width": block.width, "hint": block.hint, "error": ""}
    if block.kind == "text":
        out["paras"] = [p.strip() for p in block.text.split("\n\n") if p.strip()]
        return out
    try:
        cols, rows = run_sql(ws, block, page, values)
    except SpecError as exc:
        out["error"] = str(exc)
        return out
    except Exception as exc:  # noqa: BLE001  خطای PostgreSQL: متن کوتاه برای کاربر، جزئیات برای مدیر
        msg = str(exc).splitlines()[0] if str(exc) else type(exc).__name__
        out["error"] = "زمان اجرا تمام شد؛ پرس‌وجو سنگین است." if "statement timeout" in msg else "خواندن داده ممکن نشد."
        out["detail"] = msg[:300]
        return out
    if block.kind == "kpi":
        v = rows[0][0] if rows and rows[0] else None
        out.update(value=_fmt(v) if v is not None else "—", unit=block.unit)
    elif block.kind == "table":
        labels = dict(block.columns)
        shown = [c for c, _l in block.columns] if block.columns else cols
        idx = [cols.index(c) for c in shown if c in cols]
        out.update(headers=[labels.get(cols[i], cols[i]) for i in idx], rows=[[_fmt(r[i]) for i in idx] for r in rows],
                   truncated=len(rows) >= LIMITS["table"])
    elif block.kind == "bars":
        lower = [c.lower() for c in cols]
        if "label" not in lower or "value" not in lower:
            out["error"] = "ستون‌های «label» و «value» لازم است."
            return out
        li, vi = lower.index("label"), lower.index("value")
        top = max([float(r[vi] or 0) for r in rows] + [1.0])
        out["bars"] = [{"label": _fmt(r[li]), "value": _fmt(r[vi]), "pct": round(float(r[vi] or 0) * 100 / top)} for r in rows]
    elif block.kind == "map":
        try:
            _cols, mrows = run_sql(ws, block, page, values, kind="map")
        except Exception as exc:  # noqa: BLE001
            out["error"] = "ستون «geom» با هندسه‌ی معتبر لازم است." if "geom" in str(exc) else "خواندن داده ممکن نشد."
            return out
        feats = [{"type": "Feature", "geometry": json.loads(g), "properties": props} for g, props in mrows]
        out["geojson"] = {"type": "FeatureCollection", "features": feats}
        out["count"] = len(feats)
    return out
