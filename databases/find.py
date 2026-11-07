"""
یافتن عارضه با شرط توصیفی و مکانی (Find by attribute / location).

ورودی یک «مشخصه پرسش» JSON است که از رابط می‌آید و هرگز متن SQL نیست:

    {"layer": "public.schools", "match": "all",
     "conds": [{"col": "kind", "op": "eq", "v": "دخترانه"}],
     "spatial": {"rel": "within", "dist": 0,
                 "target": {"kind": "layer", "layer": "public.districts", "match": "all",
                            "conds": [{"col": "name", "op": "contains", "v": "نارمک"}]}}}

امنیت:
- نام جدول و ستون فقط بعد از پیدا شدن در کاتالوگ استفاده و با sql.Identifier نقل‌قول می‌شود.
- عملگر فقط از فهرست سفید OPS؛ هر مقدار کاربر به‌صورت پارامتر (%s) می‌رود.
- اجرا با نقش محدود مرورگر، اتصال فقط‌خواندنی و statement_timeout.

متن فارسی پیش از مقایسه در هر دو طرف یکسان می‌شود (ي/ی، ك/ک، ة/ه، ارقام فارسی و عربی، نیم‌فاصله).
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from psycopg import sql

from .explorer import CELL_MAX, PAGE_SIZE, Explorer, ExplorerError, TableRef

MAX_CONDS = 12
MAX_IN_VALUES = 200
COUNT_CAP = 100_000
MAP_CAP = 2000
VALUES_SAMPLE = 50_000
TIMEOUT = "20s"
MAX_SHAPE_CHARS = 200_000
MAX_DISTANCE_M = 200_000

# یکسان‌سازی متن فارسی؛ نویسه‌های اضافه‌ی FROM (نیم‌فاصله، کشیده، اعراب) حذف می‌شوند
_FROM = "يىكۀةأإؤ٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹"
_TO = "ییکههااو01234567890123456789"
_DROP = "‌‍ـًٌٍَُِّْ"
_TABLE = str.maketrans(_FROM, _TO, _DROP)


def normalize(text) -> str:
    return " ".join(str(text).translate(_TABLE).lower().split())


def _norm_sql(expr):
    """همان یکسان‌سازی در SQL (بدون جمع کردن فاصله‌های میانی که بی‌اثر است)."""
    return sql.SQL("translate(lower(btrim({e}::text)), {f}, {t})").format(
        e=expr, f=sql.Literal(_FROM + _DROP), t=sql.Literal(_TO))


class FindError(Exception):
    def __init__(self, message: str, detail: str = ""):
        super().__init__(message)
        self.detail = detail


NUMERIC = {"int2", "int4", "int8", "float4", "float8", "numeric", "oid"}
DATES = {"date", "timestamp", "timestamptz"}

# (کلید، عنوان فارسی، تعداد مقدار: 0 بی‌مقدار، 1 یک مقدار، 2 بازه، "n" فهرست)
OPS = {
    "text": [("contains", "شامل", 1), ("eq", "برابر", 1), ("ne", "نابرابر", 1), ("starts", "شروع با", 1),
             ("ends", "پایان با", 1), ("ncontains", "شامل نباشد", 1), ("in", "یکی از", "n"),
             ("empty", "خالی", 0), ("notempty", "خالی نباشد", 0)],
    "num": [("eq", "=", 1), ("ne", "≠", 1), ("gt", ">", 1), ("gte", "≥", 1), ("lt", "<", 1), ("lte", "≤", 1),
            ("between", "بین", 2), ("in", "یکی از", "n"), ("empty", "خالی", 0), ("notempty", "خالی نباشد", 0)],
    "date": [("eq", "در روز", 1), ("gte", "از", 1), ("lte", "تا", 1), ("between", "بین", 2),
             ("empty", "خالی", 0), ("notempty", "خالی نباشد", 0)],
    "bool": [("true", "بله", 0), ("false", "خیر", 0), ("empty", "خالی", 0)],
}
OP_ARITY = {kind: {k: n for k, _t, n in ops} for kind, ops in OPS.items()}

RELS = [
    ("intersects", "قطع می‌کند"), ("within", "کاملاً داخل باشد"), ("contains", "در بر بگیرد"),
    ("dwithin", "تا فاصله‌ی"), ("touches", "مجاور باشد"), ("disjoint", "هیچ تماسی نداشته باشد"),
]
REL_KEYS = {k for k, _ in RELS}
_REL_FN = {"intersects": "ST_Intersects", "within": "ST_Within", "contains": "ST_Contains", "touches": "ST_Touches"}
TARGETS = ("layer", "shape", "circle", "extent")


def column_kind(col: dict) -> str:
    if col["spatial"]:
        return "geom"
    if col["base"] in NUMERIC:
        return "num"
    if col["base"] in DATES:
        return "date"
    if col["base"] == "bool":
        return "bool"
    return "text"


def spec_hash(spec: dict) -> str:
    return hashlib.sha256(json.dumps(spec, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:40]


def uses_other_layer(spec: dict) -> bool:
    sp = spec.get("spatial") or {}
    return isinstance(sp, dict) and isinstance(sp.get("target"), dict) and sp["target"].get("kind") == "layer"


# ---------------------------------------------------------------------- مقدارها
_FA_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩٫،", "01234567890123456789.,")


def _num(value) -> str:
    text = str(value).translate(_FA_DIGITS).replace(",", "").replace("٬", "").strip()
    if not re.fullmatch(r"-?\d+(\.\d+)?", text):
        raise FindError(f"«{value}» عدد نیست.")
    return text


_DATE_RE = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")


def _date(value) -> date:
    """تاریخ میلادی (۲۰۲۶-۱۱-۰۳) یا شمسی (۱۴۰۵/۰۸/۱۲)؛ سال کمتر از ۱۷۰۰ شمسی فرض می‌شود."""
    m = _DATE_RE.fullmatch(str(value).translate(_FA_DIGITS).strip())
    if not m:
        raise FindError(f"«{value}» تاریخ نیست؛ مثلاً ۱۴۰۵/۰۸/۱۲.")
    y, mo, d = (int(x) for x in m.groups())
    try:
        if y < 1700:
            import jdatetime

            return jdatetime.date(y, mo, d).togregorian()
        return date(y, mo, d)
    except ValueError as exc:
        raise FindError(f"«{value}» تاریخ معتبری نیست.") from exc


def _like(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _values_list(value) -> list[str]:
    items = value if isinstance(value, list) else re.split(r"[\n,،؛;]+", str(value or ""))
    items = [str(x).strip() for x in items if str(x).strip()]
    if not items:
        raise FindError("دست‌کم یک مقدار برای «یکی از» وارد کنید.")
    return items[:MAX_IN_VALUES]


# ---------------------------------------------------------------------- شرط توصیفی
def _cond_sql(alias: str, col: dict, cond: dict):
    kind = column_kind(col)
    if kind == "geom":
        raise FindError("روی ستون مکانی شرط توصیفی نمی‌شود گذاشت؛ از شرط مکانی استفاده کنید.")
    op = cond.get("op")
    arity = OP_ARITY[kind].get(op)
    if arity is None:
        raise FindError(f"عملگر برای ستون «{col['name']}» نامعتبر است.")
    c = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col["name"]))
    v, v2 = cond.get("v"), cond.get("v2")
    if arity in (1, 2) and (v is None or str(v).strip() == ""):
        raise FindError(f"برای ستون «{col['name']}» مقدار وارد کنید.")
    if arity == 2 and (v2 is None or str(v2).strip() == ""):
        raise FindError(f"برای ستون «{col['name']}» هر دو سر بازه را وارد کنید.")

    if op == "empty":
        if kind == "text":
            return sql.SQL("({c} IS NULL OR btrim({c}::text) = '')").format(c=c), []
        return sql.SQL("{c} IS NULL").format(c=c), []
    if op == "notempty":
        if kind == "text":
            return sql.SQL("({c} IS NOT NULL AND btrim({c}::text) <> '')").format(c=c), []
        return sql.SQL("{c} IS NOT NULL").format(c=c), []
    if kind == "bool":
        return sql.SQL("{c} IS {b}").format(c=c, b=sql.SQL("TRUE" if op == "true" else "FALSE")), []

    if kind == "text":
        n = _norm_sql(c)
        if op == "in":
            return sql.SQL("{n} = ANY(%s)").format(n=n), [[normalize(x) for x in _values_list(v)]]
        val = normalize(v)
        if op == "eq":
            return sql.SQL("{n} = %s").format(n=n), [val]
        if op == "ne":
            return sql.SQL("({c} IS NULL OR {n} <> %s)").format(c=c, n=n), [val]
        pattern = {"contains": f"%{_like(val)}%", "ncontains": f"%{_like(val)}%",
                   "starts": f"{_like(val)}%", "ends": f"%{_like(val)}"}[op]
        if op == "ncontains":
            return sql.SQL("({c} IS NULL OR {n} NOT LIKE %s)").format(c=c, n=n), [pattern]
        return sql.SQL("{n} LIKE %s").format(n=n), [pattern]

    if kind == "num":
        if op == "in":
            return sql.SQL("{c}::numeric = ANY(%s::numeric[])").format(c=c), [[_num(x) for x in _values_list(v)]]
        if op == "between":
            lo, hi = sorted((_num(v), _num(v2)), key=float)
            return sql.SQL("{c}::numeric BETWEEN %s::numeric AND %s::numeric").format(c=c), [lo, hi]
        sym = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}[op]
        return sql.SQL("{c}::numeric {s} %s::numeric").format(c=c, s=sql.SQL(sym)), [_num(v)]

    # date: روی بخش تاریخ؛ «تا» شامل همان روز است
    d = sql.SQL("{c}::date").format(c=c)
    if op == "between":
        lo, hi = sorted((_date(v), _date(v2)))
        return sql.SQL("{d} BETWEEN %s AND %s").format(d=d), [lo, hi]
    sym = {"eq": "=", "gte": ">=", "lte": "<="}[op]
    return sql.SQL("{d} {s} %s").format(d=d, s=sql.SQL(sym)), [_date(v)]


def _conds_sql(alias: str, cols: list[dict], conds, match: str):
    if conds in (None, ""):
        conds = []
    if not isinstance(conds, list):
        raise FindError("شرط‌ها نامعتبر است.")
    if len(conds) > MAX_CONDS:
        raise FindError(f"حداکثر {MAX_CONDS} شرط.")
    by_name = {c["name"]: c for c in cols}
    parts, params = [], []
    for cond in conds:
        if not isinstance(cond, dict) or cond.get("col") not in by_name:
            raise FindError("ستون یکی از شرط‌ها در این لایه نیست.")
        s, p = _cond_sql(alias, by_name[cond["col"]], cond)
        parts.append(s)
        params += p
    if not parts:
        return None, []
    joiner = sql.SQL(" OR ") if match == "any" else sql.SQL(" AND ")
    return sql.SQL("(") + joiner.join(parts) + sql.SQL(")"), params


# ---------------------------------------------------------------------- هندسه
def _geom_info(t: TableRef, wanted: str | None) -> dict:
    if not t.geometry:
        raise FindError(f"لایه «{t.qualified}» ستون مکانی ندارد.")
    g = next((x for x in t.geometry if x["column"] == wanted), t.geometry[0])
    srid = 4326 if g["geography"] else int(g["srid"] or 0)
    return {"column": g["column"], "srid": srid, "geography": g["geography"], "type": g["type"]}


def _g(alias: str, info: dict):
    return sql.SQL("{}.{}::geometry").format(sql.Identifier(alias), sql.Identifier(info["column"]))


def _to_srid(expr, frm: int, to: int):
    """تبدیل یک عبارت هندسی از SRID frm به to؛ SRID صفر هم‌سان فرض می‌شود."""
    if frm == to:
        return expr
    if 0 in (frm, to):
        return sql.SQL("ST_SetSRID({}, {})").format(expr, sql.Literal(to))
    return sql.SQL("ST_Transform({}, {})").format(expr, sql.Literal(to))


def _to4326(alias: str, info: dict):
    g = _g(alias, info)
    if info["srid"] == 0:
        return sql.SQL("ST_SetSRID({}, 4326)").format(g)
    return g if info["srid"] == 4326 else sql.SQL("ST_Transform({}, 4326)").format(g)


def _const_geom(target: dict):
    """هدف ثابت (شکل کشیده‌شده، دایره، محدوده نقشه) به‌صورت هندسه 4326 و پارامترها."""
    kind = target.get("kind")
    if kind == "shape":
        geo = target.get("geojson")
        text = json.dumps(geo) if isinstance(geo, dict) else str(geo or "")
        if not text or len(text) > MAX_SHAPE_CHARS:
            raise FindError("شکلی روی نقشه کشیده نشده است.")
        try:
            obj = json.loads(text)
        except ValueError as exc:
            raise FindError("شکل کشیده‌شده نامعتبر است.") from exc
        if obj.get("type") == "Feature":
            obj = obj.get("geometry") or {}
        if obj.get("type") not in ("Polygon", "MultiPolygon", "LineString", "MultiLineString", "Point"):
            raise FindError("شکل کشیده‌شده نامعتبر است.")
        return sql.SQL("ST_MakeValid(ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326))"), [json.dumps(obj)]
    if kind == "circle":
        lon, lat = float(_num(target.get("lon"))), float(_num(target.get("lat")))
        r = float(_num(target.get("r")))
        if not (-180 <= lon <= 180 and -90 <= lat <= 90) or not 1 <= r <= MAX_DISTANCE_M:
            raise FindError("مرکز یا شعاع دایره نامعتبر است.")
        return sql.SQL("ST_Buffer(ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography, %s)::geometry"), [lon, lat, r]
    if kind == "extent":
        box = target.get("bbox")
        if not isinstance(box, list) or len(box) != 4:
            raise FindError("محدوده نقشه نامعتبر است.")
        w, s, e, n = (float(_num(x)) for x in box)
        w, e = max(w, -180), min(e, 180)
        s, n = max(s, -90), min(n, 90)
        if w >= e or s >= n:
            raise FindError("محدوده نقشه نامعتبر است.")
        return sql.SQL("ST_MakeEnvelope(%s, %s, %s, %s, 4326)"), [w, s, e, n]
    raise FindError("نوع هدف مکانی نامعتبر است.")


def _distance(spatial: dict) -> float:
    d = float(_num(spatial.get("dist") if spatial.get("dist") not in (None, "") else 0))
    if not 0 < d <= MAX_DISTANCE_M:
        raise FindError(f"فاصله باید بین ۱ و {MAX_DISTANCE_M:,} متر باشد.")
    return d


class Finder:
    """ساخت و اجرای پرسش روی یک پایگاه داده؛ همه‌ی ارجاع‌ها از کاتالوگ همان پایگاه."""

    def __init__(self, ex: Explorer, tables: list[TableRef] | None = None):
        self.ex = ex
        self._tables = {t.qualified: t for t in (tables if tables is not None else ex.tables())}
        self._cols: dict[str, list[dict]] = {}

    def table(self, qualified) -> TableRef:
        t = self._tables.get(str(qualified or ""))
        if t is None:
            raise FindError("لایه پیدا نشد یا به آن دسترسی ندارید.")
        return t

    def cols(self, t: TableRef) -> list[dict]:
        if t.qualified not in self._cols:
            self._cols[t.qualified] = self.ex.columns(t)
        return self._cols[t.qualified]

    # ------------------------------------------------------------------ ساخت WHERE
    def where(self, spec: dict):
        """(لایه، اطلاعات هندسه یا None، WHERE، پارامترها)"""
        if not isinstance(spec, dict):
            raise FindError("پرسش نامعتبر است.")
        t = self.table(spec.get("layer"))
        match = "any" if spec.get("match") == "any" else "all"
        parts, params = [], []
        attr, p = _conds_sql("a", self.cols(t), spec.get("conds"), match)
        if attr is not None:
            parts.append(attr)
            params += p
        info = _geom_info(t, spec.get("geom")) if t.geometry else None
        spatial = spec.get("spatial")
        if spatial:
            if info is None:
                raise FindError("این لایه ستون مکانی ندارد؛ فقط شرط توصیفی ممکن است.")
            s, p = self._spatial(info, spatial)
            parts.append(s)
            params += p
        if not parts:
            raise FindError("دست‌کم یک شرط توصیفی یا مکانی بگذارید.")
        return t, info, sql.SQL(" AND ").join(parts), params

    def _spatial(self, info: dict, spatial: dict):
        if not isinstance(spatial, dict) or spatial.get("rel") not in REL_KEYS:
            raise FindError("رابطه مکانی نامعتبر است.")
        rel = spatial["rel"]
        target = spatial.get("target") or {}
        if not isinstance(target, dict) or target.get("kind") not in TARGETS:
            raise FindError("هدف شرط مکانی را انتخاب کنید.")
        a_geom = _g("a", info)
        if target["kind"] != "layer":
            g, params = _const_geom(target)
            if rel == "dwithin":  # حریم ژئودزیک دور هدف؛ بعد قطع با نمایه مکانی لایه
                g = sql.SQL("ST_Buffer({}::geography, %s)::geometry").format(g)
                params = params + [_distance(spatial)]
            g_in_a = _to_srid(g, 4326, info["srid"])
            if rel == "disjoint":
                return sql.SQL("NOT ST_Intersects({a}, {g})").format(a=a_geom, g=g_in_a), params
            fn = _REL_FN.get(rel, "ST_Intersects")
            return sql.SQL("{fn}({a}, {g})").format(fn=sql.SQL(fn), a=a_geom, g=g_in_a), params

        # لایه‌ی دیگر (با شرط توصیفی اختیاری خودش)
        _b, _binfo, cond_b, params, _dist = self.layer_rel(info, spatial)
        exists = sql.SQL("EXISTS (SELECT 1 FROM {B} AS b WHERE {c})").format(
            B=sql.Identifier(_b.schema, _b.name), c=cond_b)
        if rel == "disjoint":
            exists = sql.SQL("NOT ") + exists
        return exists, params

    def layer_rel(self, info: dict, spatial: dict):
        """رابطه‌ی عارضه‌ی a با عارضه‌های b از لایه‌ی هدف.

        خروجی: (لایه‌ی هدف، اطلاعات هندسه‌ی آن، شرطِ روی b، پارامترها، عبارت فاصله به متر یا None).
        شرط روی b شامل «هندسه خالی نباشد»، شرط توصیفی لایه‌ی هدف و خود آزمون مکانی است.
        """
        rel = spatial["rel"]
        target = spatial.get("target") or {}
        b = self.table(target.get("layer"))
        binfo = _geom_info(b, target.get("geom"))
        b_cond, b_params = _conds_sql("b", self.cols(b), target.get("conds"),
                                      "any" if target.get("match") == "any" else "all")
        a_geom = _g("a", info)
        b_geom = _g("b", binfo)
        a_in_b = _to_srid(a_geom, info["srid"], binfo["srid"])  # نمایه‌ی مکانی لایه هدف به کار می‌آید
        params: list = []
        dist = None
        if rel == "dwithin":
            d = _distance(spatial)
            ga, gb = _to4326("a", info), _to4326("b", binfo)
            pre = sql.SQL("")
            if binfo["srid"] in (0, 4326):  # پیش‌فیلتر جعبه‌ای؛ درجه‌ی طول با کسینوس عرض بزرگ می‌شود
                pre = sql.SQL(" AND {gb} && ST_Expand({ga}, %s / (111320.0 * greatest(cos(radians(least(abs("
                              "ST_Y(ST_PointOnSurface({ga}))), 85))), 0.05)))").format(gb=b_geom, ga=ga)
                params.append(d)
            test = sql.SQL("ST_DWithin({ga}::geography, {gb}::geography, %s)").format(ga=ga, gb=gb)
            inner = sql.SQL("{pre} AND {t}").format(pre=pre, t=test)
            params.append(d)
            dist = sql.SQL("ST_Distance({ga}::geography, {gb}::geography)").format(ga=ga, gb=gb)
        else:
            fn = "ST_Intersects" if rel == "disjoint" else _REL_FN[rel]
            inner = sql.SQL(" AND {fn}({a}, {b})").format(fn=sql.SQL(fn), a=a_in_b, b=b_geom)
        cond = sql.SQL("{bg} IS NOT NULL{cond}{inner}").format(
            bg=sql.SQL("b.{}").format(sql.Identifier(binfo["column"])),
            cond=sql.SQL(" AND ") + b_cond if b_cond is not None else sql.SQL(""), inner=inner)
        return b, binfo, cond, b_params + params, dist

    # ------------------------------------------------------------------ اجرا
    def run(self, spec: dict, page: int = 1) -> dict:
        t, info, where, params = self.where(spec)
        cols = self.cols(t)
        plain = [c for c in cols if not c["spatial"]]
        page = max(int(page or 1), 1)
        rel = sql.Identifier(t.schema, t.name)
        pks = [c for c in cols if c["pk"]]
        pk_col = pks[0]["name"] if len(pks) == 1 and not pks[0]["spatial"] else ""
        order = sql.SQL(", ").join(sql.SQL("a.{}").format(sql.Identifier(c["name"])) for c in pks) if pks \
            else sql.SQL("a.ctid")
        select = sql.SQL(", ").join(sql.SQL("a.{}::text").format(sql.Identifier(c["name"])) for c in plain) \
            if plain else sql.SQL("NULL")
        g4326 = _to4326("a", info) if info else None
        geom_sel = sql.SQL(", ST_AsGeoJSON({}, 6)").format(g4326) if info else sql.SQL("")
        base = sql.SQL("FROM {rel} AS a WHERE {w}").format(rel=rel, w=where)
        if info:
            base = sql.SQL("FROM {rel} AS a WHERE a.{g} IS NOT NULL AND {w}").format(
                rel=rel, g=sql.Identifier(info["column"]), w=where)
        try:
            with self.ex.connect() as conn:
                conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(TIMEOUT)))
                total = conn.execute(sql.SQL("SELECT count(*) FROM (SELECT 1 {b} LIMIT {cap}) s").format(
                    b=base, cap=sql.Literal(COUNT_CAP + 1)), params).fetchone()[0]
                rows = conn.execute(sql.SQL("SELECT {sel}{gs} {b} ORDER BY {o} LIMIT {lim} OFFSET {off}").format(
                    sel=select, gs=geom_sel, b=base, o=order, lim=sql.Literal(PAGE_SIZE),
                    off=sql.Literal((page - 1) * PAGE_SIZE)), params).fetchall()
                features, bbox = None, None
                if info and total:
                    props = sql.SQL(", ").join(sql.SQL("{}, a.{}::text").format(sql.Literal(c["name"]),
                                                                              sql.Identifier(c["name"]))
                                               for c in plain[:40])
                    if pk_col:  # شناسه‌ی عارضه برای انتخاب دستی از روی نقشه (در پنجره‌ی اطلاعات نمایش داده نمی‌شود)
                        props = sql.SQL("{}, {}, a.{}::text").format(props, sql.Literal("__k"), sql.Identifier(pk_col)) \
                            if plain[:40] else sql.SQL("{}, a.{}::text").format(sql.Literal("__k"), sql.Identifier(pk_col))
                    features = conn.execute(sql.SQL(
                        "SELECT json_build_object('type','FeatureCollection','features', COALESCE(json_agg("
                        "json_build_object('type','Feature','geometry', ST_AsGeoJSON(s.g, 6)::json,'properties', s.p)),"
                        " '[]'::json))::text FROM (SELECT {g} AS g, {p} AS p {b} ORDER BY {o} LIMIT {cap}) s").format(
                        g=g4326, p=sql.SQL("json_build_object({})").format(props) if plain else sql.SQL("'{}'::json"),
                        b=base, o=order, cap=sql.Literal(MAP_CAP)), params).fetchone()[0]
                    ext = conn.execute(sql.SQL(
                        "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM (SELECT ST_Extent({g}) AS e "
                        "FROM (SELECT a.* {b} LIMIT {cap}) a) s").format(
                        g=g4326, b=base, cap=sql.Literal(COUNT_CAP)), params).fetchone()
                    bbox = list(ext) if ext and ext[0] is not None else None
        except (FindError, ExplorerError):
            raise
        except Exception as exc:  # خطای اجرای پرسش: کوتاه و فارسی، جزئیات جدا
            msg = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
            if "statement timeout" in msg or "canceling statement" in msg:
                raise FindError("جست‌وجو بیش از ۲۰ ثانیه طول کشید؛ شرط را محدودتر کنید یا برای ستون‌ها نمایه بسازید.") from exc
            raise FindError("اجرای جست‌وجو ممکن نشد.", msg[:300]) from exc
        out_rows = []
        names = [c["name"] for c in plain]
        for r in rows:
            vals = [("" if v is None else (v if len(v) <= CELL_MAX else v[:CELL_MAX] + "…")) for v in r[:len(plain)]] \
                if plain else []
            key = vals[names.index(pk_col)] if pk_col and vals else ""
            out_rows.append({"v": vals, "g": r[-1] if info else None, "k": key})
        return {
            "layer": t.qualified,
            "columns": names,
            "pk": pk_col,
            "rows": out_rows,
            "total": min(total, COUNT_CAP),
            "capped": total > COUNT_CAP,
            "page": page,
            "pages": max((min(total, COUNT_CAP) + PAGE_SIZE - 1) // PAGE_SIZE, 1),
            "offset": (page - 1) * PAGE_SIZE,
            "features": json.loads(features) if features else None,
            "map_capped": bool(info) and total > MAP_CAP,
            "bbox": bbox,
            "geom_type": info["type"] if info else "",
        }

    # ------------------------------------------------------------------ مقدارهای پیشنهادی
    def values(self, qualified: str, column: str) -> dict:
        t = self.table(qualified)
        col = next((c for c in self.cols(t) if c["name"] == column and not c["spatial"]), None)
        if col is None:
            raise FindError("ستون پیدا نشد.")
        kind = column_kind(col)
        c = sql.Identifier(column)
        rel = sql.Identifier(t.schema, t.name)
        with self.ex.connect() as conn:
            conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal("8s")))
            if kind in ("num", "date"):
                lo, hi = conn.execute(sql.SQL("SELECT min({c})::text, max({c})::text FROM (SELECT {c} FROM {r} "
                                              "WHERE {c} IS NOT NULL LIMIT {n}) s").format(
                    c=c, r=rel, n=sql.Literal(VALUES_SAMPLE))).fetchone()
                return {"kind": kind, "min": lo, "max": hi, "top": []}
            if kind == "bool":
                return {"kind": kind, "top": []}
            top = conn.execute(sql.SQL(
                "SELECT x, count(*) FROM (SELECT left(btrim({c}::text), 120) AS x FROM {r} WHERE {c} IS NOT NULL "
                "LIMIT {n}) s WHERE x <> '' GROUP BY x ORDER BY 2 DESC, 1 LIMIT 15").format(
                c=c, r=rel, n=sql.Literal(VALUES_SAMPLE))).fetchall()
        return {"kind": kind, "top": [{"v": v, "n": n} for v, n in top]}


def layer_catalog(finder: Finder) -> list[dict]:
    """فهرست لایه‌ها برای رابط (بدون ستون‌ها؛ ستون‌ها جدا خوانده می‌شوند)."""
    out = []
    for t in finder._tables.values():
        g = t.geometry[0] if t.geometry else None
        out.append({"key": t.qualified, "schema": t.schema, "name": t.name, "rows": t.rows_estimate,
                    "geom": (g["type"] or "GEOMETRY").upper() if g else "",
                    "geoms": [x["column"] for x in t.geometry]})
    return out


def column_catalog(finder: Finder, qualified: str) -> list[dict]:
    t = finder.table(qualified)
    return [{"name": c["name"], "kind": column_kind(c), "type": c["type"], "pk": c["pk"]} for c in finder.cols(t)]
