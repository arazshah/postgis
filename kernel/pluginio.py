"""ورود و خروج داده با handler سطح ۲ (docs/adr/0005): کد فقط تبدیل می‌کند، **هسته می‌نویسد**.

- ورود: خروجی handler اعتبارسنجی می‌شود (نام و نوع ستون از فهرست سفید، سقف ردیف/ستون، مقدار هر ستون)، سپس هسته جدول **تازه**
  می‌سازد و با INSERT پارامتری پر می‌کند. نام‌ها با Identifier می‌آیند؛ هیچ متنی از handler وارد SQL نمی‌شود.
- خروج: متن handler با نوع محتوا از فهرست سفید و نام فایل پاک‌سازی‌شده تبدیل به پاسخ دانلود می‌شود (هرگز HTML).
- هر خطا `PluginIOError` با پیام فارسی کوتاه است.
"""
from __future__ import annotations

import datetime
import json
import math
import re
from dataclasses import dataclass

from psycopg import sql
from psycopg.types.json import Jsonb

from . import tenantdb

MAX_ROWS, MAX_COLS, MAX_CELL, MAX_NAME = 20_000, 50, 10_000, 63
MAX_EXPORT = 4 * 1024 * 1024
NAME_RE = re.compile(r"[a-z_][a-z0-9_]{0,62}")
RESERVED = frozenset({"geom"})  # نام ستون هندسه‌ی ساخته‌شده توسط هسته
TYPES = {"text": "text", "integer": "integer", "bigint": "bigint", "double": "double precision", "boolean": "boolean",
         "date": "date", "timestamptz": "timestamptz", "jsonb": "jsonb"}
FORMATS = {"csv": "text/csv", "json": "application/json", "txt": "text/plain", "geojson": "application/geo+json"}
EXT = {"csv": ".csv", "json": ".json", "txt": ".txt", "geojson": ".geojson"}


class PluginIOError(ValueError):
    pass


@dataclass(frozen=True)
class Table:
    name: str
    columns: tuple[tuple[str, str], ...]  # (نام، نوع فهرست سفید)
    rows: tuple[tuple, ...]
    geometry: tuple[str, str] | None = None  # (ستون lat، ستون lon)


def table_name(raw: str) -> str:
    name = (raw or "").strip().lower()
    if not NAME_RE.fullmatch(name) or name.startswith("pg_"):
        raise PluginIOError("نام جدول نامعتبر است (حروف کوچک لاتین، رقم و _؛ با حرف شروع شود).")
    return name


def _cell(t: str, v, col: str):
    if v is None:
        return None
    try:
        if t == "text":
            if not isinstance(v, str):
                v = str(v)
            if len(v) > MAX_CELL or "\x00" in v:
                raise ValueError
            return v
        if t in ("integer", "bigint"):
            if isinstance(v, bool) or not isinstance(v, int) and not (isinstance(v, float) and v.is_integer()):
                raise ValueError
            v = int(v)
            lim = 2**31 if t == "integer" else 2**63
            if not -lim <= v < lim:
                raise ValueError
            return v
        if t == "double":
            if isinstance(v, bool):
                raise ValueError
            v = float(v)
            if not math.isfinite(v):
                raise ValueError
            return v
        if t == "boolean":
            if not isinstance(v, bool):
                raise ValueError
            return v
        if t == "date":
            if not isinstance(v, str) or len(v) < 10:
                raise ValueError
            return datetime.date.fromisoformat(v[:10])
        if t == "timestamptz":
            d = datetime.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=datetime.UTC)
        if t == "jsonb":
            if len(json.dumps(v)) > MAX_CELL:
                raise ValueError
            return Jsonb(v)
    except (ValueError, TypeError, OverflowError):
        raise PluginIOError(f"مقدار ستون «{col}» با نوع {t} نمی‌خواند.") from None
    raise PluginIOError("نوع ستون نامعتبر است.")


def normalize_import(name: str, out) -> Table:
    """خروجی handler ورود ← Table اعتبارسنجی‌شده."""
    name = table_name(name)
    if not isinstance(out, dict) or not isinstance(out.get("columns"), list) or not isinstance(out.get("rows"), list):
        raise PluginIOError("handler باید {columns: [...], rows: [[...]]} برگرداند.")
    cols = []
    for c in out["columns"]:
        if not isinstance(c, dict) or not isinstance(c.get("name"), str) or c.get("type") not in TYPES:
            raise PluginIOError("هر ستون {name, type} می‌خواهد (نوع: " + "، ".join(TYPES) + ").")
        if not NAME_RE.fullmatch(c["name"]) or c["name"] in RESERVED:
            raise PluginIOError(f"نام ستون «{c['name']}» نامعتبر است.")
        cols.append((c["name"], c["type"]))
    if not cols or len(cols) > MAX_COLS:
        raise PluginIOError(f"تعداد ستون‌ها باید بین ۱ و {MAX_COLS} باشد.")
    if len({n for n, _ in cols}) != len(cols):
        raise PluginIOError("نام ستون‌ها باید یکتا باشد.")
    if len(out["rows"]) > MAX_ROWS:
        raise PluginIOError(f"حداکثر {MAX_ROWS:,} ردیف مجاز است.")
    rows = []
    for r in out["rows"]:
        if not isinstance(r, (list, tuple)) or len(r) != len(cols):
            raise PluginIOError("طول هر ردیف باید برابر تعداد ستون‌ها باشد.")
        rows.append(tuple(_cell(t, v, n) for (n, t), v in zip(cols, r, strict=True)))
    geom = out.get("geometry")
    pair = None
    if geom is not None:
        types = dict(cols)
        if not isinstance(geom, dict) or any(types.get(geom.get(k)) != "double" for k in ("lat", "lon")):
            raise PluginIOError("geometry باید {lat, lon} با نام دو ستون double باشد.")
        pair = (geom["lat"], geom["lon"])
        for r in rows:
            la, lo = r[[n for n, _ in cols].index(pair[0])], r[[n for n, _ in cols].index(pair[1])]
            if (la is not None and not -90 <= la <= 90) or (lo is not None and not -180 <= lo <= 180):
                raise PluginIOError("مختصات خارج از بازه‌ی WGS84 است (lat ۹۰- تا ۹۰، lon ۱۸۰- تا ۱۸۰).")
    return Table(name, tuple(cols), tuple(rows), pair)


def statements(t: Table):
    """(CREATE TABLE، INSERT) برای جدول تازه؛ مقدارها فقط جای‌نگهدار هستند."""
    rel = sql.Identifier("public", t.name)
    defs = [sql.SQL("{} {}").format(sql.Identifier(n), sql.SQL(TYPES[ty])) for n, ty in t.columns]
    names = [n for n, _ in t.columns]
    cols_sql = sql.SQL(", ").join(sql.Identifier(n) for n in names)
    vals = [sql.Placeholder() for _ in names]
    if t.geometry:
        defs.append(sql.SQL("geom geometry(Point, 4326)"))
        cols_sql = sql.SQL("{}, geom").format(cols_sql)
        num = sql.SQL("CAST(%s AS double precision)")  # بدون cast نوع پارامترِ «IS NULL» مشخص نیست (IndeterminateDatatype)
        vals.append(sql.SQL("CASE WHEN {} IS NULL OR {} IS NULL THEN NULL ELSE ST_SetSRID(ST_MakePoint({}, {}), 4326) END").format(
            num, num, num, num))
    create = sql.SQL("CREATE TABLE {} ({})").format(rel, sql.SQL(", ").join(defs))
    insert = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(rel, cols_sql, sql.SQL(", ").join(vals))
    return create, insert


def create_table(ws, t: Table) -> int:
    """جدول تازه‌ی public.<name> را با نقش مالک می‌سازد و ردیف‌ها را با INSERT پارامتری می‌ریزد؛ تعداد ردیف."""
    cat = tenantdb.catalog(ws)
    if any(x.schema == "public" and x.name == t.name for x in cat.tables()):
        raise PluginIOError(f"جدولی به نام «{t.name}» از قبل هست؛ نام دیگری بدهید.")
    create, insert = statements(t)
    names = [n for n, _ in t.columns]
    la, lo = (names.index(t.geometry[0]), names.index(t.geometry[1])) if t.geometry else (None, None)
    with tenantdb.connect(ws, write=True, as_owner=True) as conn:
        conn.execute(sql.SQL("SET LOCAL statement_timeout = '30s'"))
        conn.execute(create)
        with conn.cursor() as cur:
            if t.geometry:
                # ترتیب جای‌نگهدارها: (lat IS NULL، lon IS NULL، lon، lat) برای ST_MakePoint(lon, lat)
                cur.executemany(insert, [r + (r[la], r[lo], r[lo], r[la]) for r in t.rows])
            else:
                cur.executemany(insert, t.rows)
        conn.commit()
    return len(t.rows)


def safe_filename(raw, fmt: str) -> str:
    base = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(raw or "export").rsplit("/", 1)[-1]).strip("._") or "export"
    base = re.sub(r"\.(csv|json|txt|geojson)$", "", base, flags=re.I)[:60] or "export"
    return base + EXT[fmt]


def normalize_export(out, fmt: str) -> tuple[str, bytes, str]:
    """خروجی handler خروج ← (نام فایل، بایت‌ها، Content-Type از فهرست سفید)."""
    if fmt not in FORMATS:
        raise PluginIOError("قالب خروجی نامعتبر است.")
    if not isinstance(out, dict) or not isinstance(out.get("text"), str):
        raise PluginIOError("handler باید {filename, text} برگرداند.")
    data = out["text"].encode("utf-8")
    if len(data) > MAX_EXPORT:
        raise PluginIOError("خروجی بیش از ۴ مگابایت است.")
    if fmt in ("json", "geojson"):
        try:
            json.loads(out["text"])
        except ValueError:
            raise PluginIOError("خروجی JSON معتبر نیست.") from None
    return safe_filename(out.get("filename"), fmt), data, FORMATS[fmt]
