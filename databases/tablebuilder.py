"""
سازنده‌ی جدول: اعتبارسنجی مشخصات جدولی که کاربر از رابط تعریف می‌کند و تولید دستورهای DDL.

امنیت: هیچ SQL خامی از کاربر پذیرفته نمی‌شود.
- نوع ستون‌ها فقط از فهرست سفید `TYPES` می‌آید و پارامترهای عددی (طول، دقت) عدد صحیح محدودند.
- نام‌ها با الگوی سخت‌گیر بررسی و با sql.Identifier نقل‌قول می‌شوند.
- مقدار پیش‌فرض یا از قالب‌های ثابت است (@now، @uuid) یا با sql.Literal و بر اساس نوع ستون ساخته می‌شود.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from psycopg import sql

MAX_COLUMNS = 200
MAX_INDEXES = 20
MAX_CHOICES = 50
MAX_CHOICE_LEN = 60
MAX_COMMENT = 500
NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

# واژه‌های رزروشده‌ی PostgreSQL که به‌عنوان نام ستون یا جدول مناسب نیستند
RESERVED = frozenset("""
all analyse analyze and any array as asc asymmetric authorization binary both case cast check collate collation column
concurrently constraint create cross current_catalog current_date current_role current_schema current_time
current_timestamp current_user default deferrable desc distinct do else end except false fetch for foreign freeze from
full grant group having ilike in initially inner intersect into is isnull join lateral leading left like limit
localtime localtimestamp natural not notnull null offset on only or order outer overlaps placing primary references
returning right select session_user similar some symmetric table tablesample then to trailing true union unique user
using variadic verbose when where window with
""".split())

GEOMETRY_TYPES = {
    "Point": "نقطه", "LineString": "خط", "Polygon": "چندضلعی", "MultiPoint": "چندنقطه",
    "MultiLineString": "چندخط", "MultiPolygon": "چندچندضلعی", "Geometry": "مختلط",
}
DIMENSIONS = {"XY": "", "XYZ": "Z", "XYM": "M"}

# کلید → (برچسب فارسی، گروه، نوع SQL، پارامتر)
TYPES: dict[str, dict] = {
    "text": {"label": "متن", "group": "متن", "sql": "text"},
    "varchar": {"label": "متن کوتاه (با سقف طول)", "group": "متن", "sql": "varchar", "param": "length"},
    "choice": {"label": "فهرست انتخابی", "group": "متن", "sql": "text", "param": "choices"},
    "smallint": {"label": "عدد صحیح کوچک", "group": "عدد", "sql": "smallint"},
    "integer": {"label": "عدد صحیح", "group": "عدد", "sql": "integer"},
    "bigint": {"label": "عدد صحیح بزرگ", "group": "عدد", "sql": "bigint"},
    "double": {"label": "عدد اعشاری", "group": "عدد", "sql": "double precision"},
    "numeric": {"label": "عدد دقیق (دقت‌دار)", "group": "عدد", "sql": "numeric", "param": "precision"},
    "boolean": {"label": "بله/خیر", "group": "منطقی", "sql": "boolean"},
    "date": {"label": "تاریخ", "group": "زمان", "sql": "date"},
    "timestamptz": {"label": "تاریخ و زمان", "group": "زمان", "sql": "timestamptz"},
    "time": {"label": "ساعت", "group": "زمان", "sql": "time"},
    "jsonb": {"label": "JSON", "group": "ساختاریافته", "sql": "jsonb"},
    "uuid": {"label": "شناسه‌ی یکتا (UUID)", "group": "ساختاریافته", "sql": "uuid"},
    "text_array": {"label": "فهرست متنی", "group": "ساختاریافته", "sql": "text[]"},
}
_INT_TYPES = {"smallint", "integer", "bigint"}
_TEMPLATE_DEFAULTS = {"@now": ("date", "timestamptz", "time"), "@uuid": ("uuid",)}
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{2}:\d{2}(:\d{2})?$")
_TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2})?$")
_NUM_RE = re.compile(r"^-?\d+(\.\d+)?$")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")

# قالب‌های آماده؛ فقط مشخصات پیش‌فرض‌اند و کاربر پیش از ساخت می‌تواند همه را عوض کند
PRESETS = {
    "points": {"label": "نقاط با نام و توضیح", "icon": "point", "geometry": {"type": "Point"},
               "columns": [{"name": "name", "type": "text", "label": "نام"},
                           {"name": "descr", "type": "text", "label": "توضیح"}]},
    "parcels": {"label": "قطعه‌زمین", "icon": "polygon", "geometry": {"type": "Polygon"},
                "columns": [{"name": "code", "type": "text", "not_null": True, "unique": True, "label": "کد قطعه"},
                            {"name": "owner", "type": "text", "label": "مالک"},
                            {"name": "area_m2", "type": "double", "label": "مساحت (مترمربع)"},
                            {"name": "surveyed_on", "type": "date", "label": "تاریخ برداشت"}]},
    "routes": {"label": "مسیر", "icon": "line", "geometry": {"type": "LineString"},
               "columns": [{"name": "name", "type": "text", "label": "نام"},
                           {"name": "length_m", "type": "double", "label": "طول (متر)"},
                           {"name": "status", "type": "choice", "choices": ["فعال", "در دست ساخت", "مسدود"],
                            "label": "وضعیت"}]},
    "poi": {"label": "نقطه‌ی مورد علاقه (POI)", "icon": "target", "geometry": {"type": "Point"},
            "columns": [{"name": "name", "type": "text", "not_null": True, "label": "نام"},
                        {"name": "category", "type": "choice", "choices": ["اداری", "درمانی", "آموزشی", "تجاری"],
                         "label": "دسته"},
                        {"name": "phone", "type": "text", "label": "تلفن"},
                        {"name": "visited_at", "type": "timestamptz", "default": "@now", "label": "زمان ثبت"}]},
    "plain": {"label": "جدول ساده (بدون هندسه)", "icon": "table", "geometry": None,
              "columns": [{"name": "name", "type": "text", "label": "نام"}]},
}


class BuildError(Exception):
    """خطای مشخصات؛ پیام فارسی و قابل نمایش به کاربر است."""


@dataclass
class Plan:
    spec: dict
    statements: list

    def script(self) -> str:
        return ";\n\n".join(s.as_string(None) for s in self.statements) + ";"


def check_name(value, what: str = "نام") -> str:
    name = value.strip() if isinstance(value, str) else ""
    if not name:
        raise BuildError(f"{what} را وارد کنید.")
    if not NAME_RE.match(name):
        raise BuildError(f"{what} «{name}» نامعتبر است؛ فقط حروف کوچک لاتین، رقم و _ (با شروع از حرف) و حداکثر ۶۳ نویسه.")
    if name in RESERVED or name.startswith("pg_"):
        raise BuildError(f"{what} «{name}» واژه‌ی رزروشده است؛ نام دیگری انتخاب کنید.")
    return name


def _int(value, lo: int, hi: int, what: str) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise BuildError(f"{what} باید عدد باشد.") from None
    if not lo <= n <= hi:
        raise BuildError(f"{what} باید بین {lo} و {hi} باشد.")
    return n


def _geometry(raw) -> dict | None:
    if raw in (None, False, {}):
        return None
    if not isinstance(raw, dict):
        raise BuildError("مشخصات هندسه نامعتبر است.")
    gtype = raw.get("type")
    if gtype not in GEOMETRY_TYPES:
        raise BuildError("نوع هندسه نامعتبر است.")
    dim = raw.get("dim") or "XY"
    if dim not in DIMENSIONS:
        raise BuildError("بُعد هندسه نامعتبر است.")
    geography = bool(raw.get("geography"))
    srid = _int(raw.get("srid", 4326), 1, 998999, "SRID")
    if geography and srid != 4326:
        raise BuildError("geography فقط با SRID ‏۴۳۲۶ پشتیبانی می‌شود.")
    if geography and gtype == "Geometry":
        raise BuildError("نوع «مختلط» فقط برای geometry است.")
    return {"name": check_name(raw.get("name") or "geom", "نام ستون هندسه"), "type": gtype, "dim": dim,
            "srid": srid, "geography": geography, "not_null": bool(raw.get("not_null")),
            "index": raw.get("index") is not False}


def _choices(raw) -> list[str]:
    if not isinstance(raw, list):
        raise BuildError("گزینه‌های فهرست انتخابی نامعتبر است.")
    out = []
    for c in raw:
        s = str(c).strip() if isinstance(c, (str, int, float)) else ""
        if not s:
            continue
        if len(s) > MAX_CHOICE_LEN or "\x00" in s:
            raise BuildError(f"هر گزینه حداکثر {MAX_CHOICE_LEN} نویسه است.")
        if s not in out:
            out.append(s)
    if not out:
        raise BuildError("برای فهرست انتخابی دست‌کم یک گزینه بنویسید.")
    if len(out) > MAX_CHOICES:
        raise BuildError(f"حداکثر {MAX_CHOICES} گزینه مجاز است.")
    return out


def _default(kind: str, raw, name: str):
    """مقدار پیش‌فرض را بررسی می‌کند و (نوع، مقدار) برمی‌گرداند؛ None یعنی بدون پیش‌فرض."""
    if raw is None or raw == "":
        return None
    if isinstance(raw, bool):
        raw = "true" if raw else "false"
    if not isinstance(raw, (str, int, float)):
        raise BuildError(f"مقدار پیش‌فرض «{name}» نامعتبر است.")
    s = str(raw).strip()
    if s in _TEMPLATE_DEFAULTS:
        if kind not in _TEMPLATE_DEFAULTS[s]:
            raise BuildError(f"مقدار پیش‌فرض خودکار برای ستون «{name}» با نوعش سازگار نیست.")
        return ("tmpl", s)
    if len(s) > 500 or "\x00" in s:
        raise BuildError(f"مقدار پیش‌فرض «{name}» نامعتبر یا بلند است.")
    bad = BuildError(f"مقدار پیش‌فرض «{name}» با نوع ستون سازگار نیست.")
    if kind in _INT_TYPES:
        if not re.fullmatch(r"-?\d+", s):
            raise bad
        return ("lit", int(s))
    if kind in ("double", "numeric"):
        if not _NUM_RE.match(s):
            raise bad
        return ("lit", s)
    if kind == "boolean":
        if s.lower() not in ("true", "false"):
            raise bad
        return ("lit", s.lower() == "true")
    if kind == "date" and not _DATE_RE.match(s):
        raise bad
    if kind == "time" and not _TIME_RE.match(s):
        raise bad
    if kind == "timestamptz" and not _TS_RE.match(s):
        raise bad
    if kind == "uuid" and not _UUID_RE.match(s):
        raise bad
    if kind in ("jsonb", "text_array"):
        raise BuildError(f"برای نوع این ستون («{name}») مقدار پیش‌فرض ثابت پشتیبانی نمی‌شود.")
    return ("lit", s)


def _column(raw, taken: set[str]) -> dict:
    if not isinstance(raw, dict):
        raise BuildError("مشخصات ستون نامعتبر است.")
    name = check_name(raw.get("name"), "نام ستون")
    if name in taken:
        raise BuildError(f"نام ستون «{name}» تکراری است.")
    kind = raw.get("type")
    if kind not in TYPES:
        raise BuildError(f"نوع ستون «{name}» نامعتبر است.")
    col = {"name": name, "type": kind, "not_null": bool(raw.get("not_null")), "unique": bool(raw.get("unique"))}
    param = TYPES[kind].get("param")
    if param == "length":
        col["length"] = _int(raw.get("length", 255), 1, 10485760, f"طول ستون «{name}»")
    elif param == "precision":
        col["precision"] = _int(raw.get("precision", 12), 1, 38, f"دقت ستون «{name}»")
        col["scale"] = _int(raw.get("scale", 2), 0, col["precision"], f"تعداد رقم اعشار «{name}»")
    elif param == "choices":
        col["choices"] = _choices(raw.get("choices"))
    default = _default(kind, raw.get("default"), name)
    if default:
        col["default"] = raw.get("default") if default[0] == "tmpl" else str(raw.get("default")).strip()
    if kind == "choice" and col.get("default") and col["default"] not in col["choices"]:
        raise BuildError(f"مقدار پیش‌فرض «{name}» باید یکی از گزینه‌ها باشد.")
    return col


def validate(raw) -> dict:
    """مشخصات خام را اعتبارسنجی و به شکل یکنواخت درمی‌آورد؛ هرچه ناشناخته باشد رد می‌شود."""
    if not isinstance(raw, dict):
        raise BuildError("درخواست نامعتبر است.")
    spec = {"schema": check_name(raw.get("schema") or "public", "نام schema"),
            "name": check_name(raw.get("name"), "نام جدول")}
    comment = raw.get("comment")
    spec["comment"] = comment.strip()[:MAX_COMMENT] if isinstance(comment, str) else ""
    if "\x00" in spec["comment"]:
        raise BuildError("توضیح جدول نویسه‌ی نامعتبر دارد.")
    spec["geometry"] = _geometry(raw.get("geometry"))
    taken = {spec["geometry"]["name"]} if spec["geometry"] else set()

    pk = raw.get("pk") if isinstance(raw.get("pk"), dict) else {}
    mode = pk.get("mode") or "identity"
    if mode not in ("identity", "columns", "none"):
        raise BuildError("نوع کلید اصلی نامعتبر است.")
    pk_name = None
    if mode == "identity":
        pk_name = check_name(pk.get("name") or "id", "نام ستون کلید اصلی")
        taken.add(pk_name)
        pk_big = pk.get("big", True) is not False
    cols_raw = raw.get("columns") or []
    if not isinstance(cols_raw, list):
        raise BuildError("فهرست ستون‌ها نامعتبر است.")
    if len(cols_raw) + len(taken) > MAX_COLUMNS:
        raise BuildError(f"حداکثر {MAX_COLUMNS} ستون در هر جدول مجاز است.")
    columns = []
    for c in cols_raw:
        col = _column(c, taken)
        taken.add(col["name"])
        columns.append(col)
    spec["columns"] = columns
    names = {c["name"] for c in columns}

    if mode == "identity":
        spec["pk"] = {"mode": "identity", "name": pk_name, "big": pk_big}
    elif mode == "columns":
        pcols = pk.get("columns")
        if not isinstance(pcols, list) or not pcols or len(set(pcols)) != len(pcols):
            raise BuildError("برای کلید اصلی دست‌کم یک ستون انتخاب کنید.")
        for p in pcols:
            if p not in names:
                raise BuildError(f"ستون کلید اصلی «{p}» در جدول نیست.")
            if next(c for c in columns if c["name"] == p)["type"] in ("jsonb", "text_array"):
                raise BuildError(f"ستون «{p}» از این نوع نمی‌تواند کلید اصلی باشد.")
        spec["pk"] = {"mode": "columns", "columns": pcols}
    else:
        spec["pk"] = {"mode": "none"}

    idx_raw = raw.get("indexes") or []
    if not isinstance(idx_raw, list) or len(idx_raw) > MAX_INDEXES:
        raise BuildError(f"حداکثر {MAX_INDEXES} ایندکس مجاز است.")
    indexes, seen = [], set()
    for i in idx_raw:
        cols = i.get("columns") if isinstance(i, dict) else None
        if not isinstance(cols, list) or not cols or len(cols) > 8:
            raise BuildError("هر ایندکس یک تا هشت ستون دارد.")
        for c in cols:
            if c not in names:
                raise BuildError(f"ستون ایندکس «{c}» در جدول نیست.")
            if next(x for x in columns if x["name"] == c)["type"] == "jsonb":
                raise BuildError(f"روی ستون JSON ایندکس معمولی ساخته نمی‌شود («{c}»).")
        key = tuple(cols)
        if key not in seen:
            seen.add(key)
            indexes.append({"columns": list(cols), "unique": bool(i.get("unique"))})
    spec["indexes"] = indexes
    return spec


def _type_sql(col: dict) -> sql.Composable:
    kind = col["type"]
    if kind == "varchar":
        return sql.SQL("varchar({})").format(sql.Literal(col["length"]))
    if kind == "numeric":
        return sql.SQL("numeric({}, {})").format(sql.Literal(col["precision"]), sql.Literal(col["scale"]))
    return sql.SQL(TYPES[kind]["sql"])


def _geom_type_sql(g: dict) -> sql.Composable:
    gtype = g["type"] + DIMENSIONS[g["dim"]]
    kind = "geography" if g["geography"] else "geometry"
    return sql.SQL("{}({}, {})").format(sql.SQL(kind), sql.SQL(gtype), sql.Literal(g["srid"]))


def _default_sql(col: dict) -> sql.Composable | None:
    raw = col.get("default")
    if raw is None:
        return None
    kind = col["type"]
    if raw == "@now":
        return sql.SQL({"date": "CURRENT_DATE", "timestamptz": "now()", "time": "CURRENT_TIME"}[kind])
    if raw == "@uuid":
        return sql.SQL("gen_random_uuid()")
    _, value = _default(kind, raw, col["name"])
    lit = sql.Literal(value)
    if kind in ("date", "timestamptz", "time", "uuid", "numeric", "double"):
        return sql.SQL("{}::{}").format(lit, _type_sql(col))
    return lit


def column_sql(c: dict) -> sql.Composable:
    """تعریف یک ستون (نام، نوع، پیش‌فرض، قیدها) برای CREATE TABLE و ADD COLUMN."""
    bits: list[sql.Composable] = [sql.Identifier(c["name"]), _type_sql(c)]
    default = _default_sql(c)
    if default is not None:
        bits += [sql.SQL("DEFAULT"), default]
    if c["not_null"]:
        bits.append(sql.SQL("NOT NULL"))
    if c["unique"]:
        bits.append(sql.SQL("UNIQUE"))
    if c["type"] == "choice":
        bits.append(sql.SQL("CHECK ({} IN ({}))").format(
            sql.Identifier(c["name"]), sql.SQL(", ").join(sql.Literal(x) for x in c["choices"])))
    return sql.SQL(" ").join(bits)


def build(raw) -> Plan:
    """دستورهای ساخت جدول (CREATE TABLE، ایندکس‌ها، توضیح) را از مشخصات می‌سازد."""
    spec = validate(raw)
    rel = sql.Identifier(spec["schema"], spec["name"])
    parts: list[sql.Composable] = []
    pk = spec["pk"]
    if pk["mode"] == "identity":
        parts.append(sql.SQL("{} {} GENERATED ALWAYS AS IDENTITY PRIMARY KEY").format(
            sql.Identifier(pk["name"]), sql.SQL("bigint" if pk["big"] else "integer")))
    for c in spec["columns"]:
        parts.append(column_sql(c))
    g = spec["geometry"]
    if g:
        parts.append(sql.SQL("{} {}{}").format(sql.Identifier(g["name"]), _geom_type_sql(g),
                                                sql.SQL(" NOT NULL" if g["not_null"] else "")))
    if pk["mode"] == "columns":
        parts.append(sql.SQL("PRIMARY KEY ({})").format(sql.SQL(", ").join(sql.Identifier(p) for p in pk["columns"])))
    stmts: list[sql.Composable] = [sql.SQL("CREATE TABLE {} (\n  {}\n)").format(rel, sql.SQL(",\n  ").join(parts))]
    if g and g["index"]:
        stmts.append(sql.SQL("CREATE INDEX {} ON {} USING gist ({})").format(
            sql.Identifier(f"{spec['name']}_{g['name']}_gix"[:63]), rel, sql.Identifier(g["name"])))
    for i in spec["indexes"]:
        iname = f"{spec['name']}_{'_'.join(i['columns'])}_idx"[:63]
        stmts.append(sql.SQL("CREATE {}INDEX {} ON {} ({})").format(
            sql.SQL("UNIQUE " if i["unique"] else ""), sql.Identifier(iname), rel,
            sql.SQL(", ").join(sql.Identifier(c) for c in i["columns"])))
    if spec["comment"]:
        stmts.append(sql.SQL("COMMENT ON TABLE {} IS {}").format(rel, sql.Literal(spec["comment"])))
    return Plan(spec, stmts)


def client_config() -> dict:
    """فراداده‌ی ثابت برای سازنده‌ی جاوااسکریپتی (نوع‌ها و قالب‌ها)."""
    return {
        "types": [{"key": k, "label": v["label"], "group": v["group"], "param": v.get("param", "")}
                  for k, v in TYPES.items()],
        "geometry_types": [{"key": k, "label": v} for k, v in GEOMETRY_TYPES.items()],
        "presets": [{"key": k, **v} for k, v in PRESETS.items()],
        "limits": {"columns": MAX_COLUMNS, "indexes": MAX_INDEXES, "choices": MAX_CHOICES},
    }
