"""
تحلیل‌های آماده بدون SQL: هر ابزار یک جدول جدید در پایگاه داده کاربر می‌سازد (با نقش خود کاربر).

همه فاصله‌ها به متر و روی geography (WGS84) حساب می‌شوند تا SRID جدول‌ها مهم نباشد.
"""
from __future__ import annotations

from dataclasses import dataclass

from psycopg import sql

from databases.explorer import Explorer, ExplorerError, TableRef
from databases.gdal import TABLE_RE

TIMEOUT = "180s"


class ToolError(Exception):
    pass


@dataclass(frozen=True)
class Tool:
    key: str
    title: str
    description: str
    icon: str


TOOLS = [
    Tool("buffer", "حریم (بافر)", "دور هر عارضه حریمی به فاصله دلخواه می‌کشد؛ مثلاً حریم ۵۰۰ متری ایستگاه‌ها.", "buffer"),
    Tool("nearest", "نزدیک‌ترین عارضه", "برای هر عارضه، نزدیک‌ترین عارضه لایه دیگر و فاصله‌اش به متر.", "nearest"),
    Tool("count", "شمارش در چندضلعی", "تعداد نقطه‌های یک لایه داخل هر چندضلعی؛ مثلاً مدرسه‌های هر محله.", "count"),
    Tool("overlap", "سهم همپوشانی", "سهم هر دسته (مثلاً کاربری زمین) از مساحت هر چندضلعی (مثلاً محله) با برش دو لایه چندضلعی.", "overlap"),
    Tool("change", "تغییر بین دو نسخه", "دو نسخه‌ی یک لایه چندضلعی (مثلاً کاربری ۱۴۰۰ و ۱۴۰۵) را برش می‌دهد و مساحت هر «از ← به» را می‌دهد.", "change"),
    Tool("hexbin", "نقشه تراکم شش‌ضلعی", "شبکه شش‌ضلعی روی نقطه‌ها و تعداد هر خانه؛ برای نقشه حرارتی.", "hexbin"),
    Tool("isochrone", "حوزه دسترسی", "محدوده‌ای که از یک نقطه با پیمودن فاصله مشخص روی شبکه معابر می‌رسید.", "isochrone"),
    Tool("within", "انتخاب بر اساس فاصله", "عارضه‌های یک لایه را که تا فاصله‌ی مشخصی از لایه‌ی دیگر هستند جدا می‌کند و تعداد همسایه‌ها را کنارشان می‌گذارد.", "within"),
    Tool("voronoi", "حوزه نفوذ (تیسن)", "هر نقطه از محدوده را به نزدیک‌ترین مرکز نسبت می‌دهد؛ برای حوزه‌ی خدمات کلانتری‌ها یا شعبه‌ها.", "voronoi"),
    Tool("cluster", "خوشه‌بندی نقطه‌ها", "نقطه‌های نزدیک به هم را خوشه می‌کند و دور هر خوشه چندضلعی و تعدادش را می‌دهد؛ برای یافتن کانون‌ها.", "cluster"),
    Tool("measure", "طول و مساحت در چندضلعی", "مجموع طول خط‌ها یا مساحت چندضلعی‌های یک لایه را داخل هر چندضلعی حساب می‌کند.", "measure"),
    Tool("clip", "برش با مرز", "هر لایه‌ای را با یک مرز چندضلعی می‌بُرد و فقط بخش داخل مرز را نگه می‌دارد.", "clip"),
    Tool("erase", "حذف ناحیه", "بخشی از لایه چندضلعی را که زیر لایه‌ی چندضلعی دیگر قرار دارد حذف می‌کند.", "erase"),
    Tool("route", "کوتاه‌ترین مسیر", "کوتاه‌ترین مسیر روی شبکه معابر بین دو نقطه، با طول آن به متر.", "route"),
    Tool("netnearest", "نزدیک‌ترین روی شبکه", "برای هر نقطه نزدیک‌ترین مرکز را با فاصله‌ی واقعی روی خیابان‌ها پیدا می‌کند.", "netnearest"),
    Tool("coverage", "پوشش چند مرکز", "حوزه‌ی دسترسی روی شبکه معابر را برای همه‌ی نقطه‌های یک لایه می‌سازد و هر بخش را به نزدیک‌ترین مرکز می‌دهد.", "coverage"),
]
TOOL_MAP = {t.key: t for t in TOOLS}


def _fix_geom_type(conn, target) -> None:
    """ستون geom حاصل از عبارت، نوع و SRID ندارد (geometry خالی) و QGIS و نقشه آن را بدون مختصات می‌بینند؛
    نوع را از خود داده (و Multi اگر تک و چندبخشی قاطی باشند) و SRID را 4326 می‌گذارد."""
    types = {r[0] for r in conn.execute(sql.SQL("SELECT DISTINCT GeometryType(geom) FROM {} WHERE geom IS NOT NULL")
                                        .format(target)).fetchall()}
    base = {t.removeprefix("MULTI") for t in types}
    if len(types) == 1:
        gtype, expr = types.pop(), "ST_SetSRID(geom, 4326)"
    elif len(base) == 1 and base.pop() in ("POINT", "LINESTRING", "POLYGON"):
        gtype, expr = "MULTI" + next(iter(types)).removeprefix("MULTI"), "ST_Multi(ST_SetSRID(geom, 4326))"
    else:
        gtype, expr = "GEOMETRY", "ST_SetSRID(geom, 4326)"
    conn.execute(sql.SQL("ALTER TABLE {} ALTER COLUMN geom TYPE geometry({}, 4326) USING " + expr).format(
        target, sql.SQL(gtype)))


def _geom4326(alias: str, col: str, srid: int):
    g = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid in (0, 4326):
        return sql.SQL("ST_SetSRID({}::geometry, 4326)").format(g)
    return sql.SQL("ST_Transform({}::geometry, 4326)").format(g)


def _attrs(ex: Explorer, t: TableRef, alias: str, prefix: str = "", exclude=()) -> list:
    out = []
    for c in ex.columns(t):
        if c["spatial"] or c["name"] in exclude or c["name"] in ("gid",):
            continue
        out.append(sql.SQL("{}.{} AS {}").format(sql.Identifier(alias), sql.Identifier(c["name"]),
                                                 sql.Identifier(f"{prefix}{c['name']}"[:63])))
    return out


def _geom_of(t: TableRef, want: tuple[str, ...] | None = None, ex: Explorer | None = None) -> tuple[str, int, str]:
    if not t.geometry:
        raise ToolError(f"جدول {t.name} ستون مکانی ندارد.")
    g = t.geometry[0]
    gtype = (g.get("type") or "").upper()
    if want and gtype in ("GEOMETRY", "") and ex is not None:
        # ستون با نوع عمومی: نوع واقعی چند ردیف اول
        with ex.connect() as conn:
            rows = conn.execute(sql.SQL("SELECT DISTINCT GeometryType({c}) FROM (SELECT {c} FROM {t} WHERE {c} IS NOT NULL "
                                        "LIMIT 200) s").format(c=sql.Identifier(g["column"]),
                                                               t=sql.Identifier(t.schema, t.name))).fetchall()
        gtype = ",".join(sorted(r[0] for r in rows if r[0])) or gtype
    if want and not any(w in gtype for w in want) and gtype not in ("GEOMETRY", ""):
        raise ToolError(f"جدول {t.name} از نوع {gtype} است؛ این ابزار {'/'.join(want)} می‌خواهد.")
    return g["column"], int(g.get("srid") or 0), gtype


NUMERIC = {"int2", "int4", "int8", "float4", "float8", "numeric"}


def _in_srid(alias: str, col: str, srid: int, target: int):
    """ستون مکانی در SRID لایه دیگر، برای شرط ST_Intersects (نمایه مکانی لایه اول)."""
    ident = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid != target and srid != 0 and target != 0:
        return sql.SQL("ST_Transform({}, {})").format(ident, sql.Literal(target))
    return ident


def _cols(ex, t):
    return {c["name"] for c in ex.columns(t)}


def _prepare(db, key: str, params: dict):
    """اعتبارسنجی پارامترها و ساخت SELECT نهایی؛ به پایگاه داده کاربر فقط کاتالوگ را می‌خواند."""
    if key not in TOOL_MAP:
        raise ToolError("ابزار ناشناخته است.")
    out = (params.get("output") or "").strip().lower()
    if not TABLE_RE.match(out):
        raise ToolError("نام جدول خروجی: حروف کوچک لاتین، رقم و _ (مثلاً metro_buffer_500).")
    ex = Explorer(db)
    tables = {f"{t.schema}.{t.name}": t for t in ex.tables()}
    if f"public.{out}" in tables and params.get("replace") != "on":
        raise ToolError(f"جدول {out} از قبل وجود دارد؛ نام دیگری بدهید یا «جایگزین شود» را بزنید.")

    def table(name_key):
        t = tables.get(params.get(name_key) or "")
        if t is None:
            raise ToolError("لایه انتخاب نشده یا وجود ندارد.")
        return t

    def number(k, lo, hi):
        try:
            v = float(str(params.get(k, "")).replace(",", "").translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")))
        except ValueError as exc:
            raise ToolError("عدد نامعتبر است.") from exc
        if not lo <= v <= hi:
            raise ToolError(f"مقدار باید بین {lo:g} و {hi:g} باشد.")
        return v

    target = sql.Identifier("public", out)
    guards: list = []  # (پرس‌وجوی شمارش، سقف، پیام): بررسی پیش از ساخت جدول در run

    def guard(t, col, cap, msg):
        guards.append((sql.SQL("SELECT count(*) FROM (SELECT 1 FROM {} WHERE {} IS NOT NULL LIMIT {}) x").format(
            sql.Identifier(t.schema, t.name), sql.Identifier(col), sql.Literal(cap + 1)), cap, msg))

    def need_routing():
        if "routing.ways" not in tables:
            raise ToolError("شبکه معابر (routing.ways) ندارید؛ از «داده آماده ایران» شبکه مسیریابی بگیرید.")

    if key == "buffer":
        t = table("layer")
        col, srid, _ = _geom_of(t)
        d = number("distance", 1, 100_000)
        attrs = _attrs(ex, t, "s")
        g = _geom4326("s", col, srid)
        if params.get("dissolve") == "on":
            body = sql.SQL("SELECT ST_Multi(ST_Union(ST_Buffer({g}::geography, {d})::geometry))::geometry(MultiPolygon, 4326)"
                           " AS geom FROM {src} s").format(g=g, d=sql.Literal(d), src=sql.Identifier(t.schema, t.name))
        else:
            body = sql.SQL("SELECT {attrs}ST_Buffer({g}::geography, {d})::geometry(Polygon, 4326) AS geom "
                           "FROM {src} s WHERE s.{c} IS NOT NULL").format(
                attrs=sql.SQL(", ").join(attrs) + sql.SQL(", ") if attrs else sql.SQL(""), g=g, d=sql.Literal(d),
                src=sql.Identifier(t.schema, t.name), c=sql.Identifier(col))
    elif key == "nearest":
        a, b = table("layer"), table("other")
        ca, sa, _ = _geom_of(a)
        cb, sb, _ = _geom_of(b)
        label = params.get("label") or ""
        if label and label not in _cols(ex, b):
            raise ToolError("ستون نام لایه دوم نامعتبر است.")
        ga = _geom4326("a", ca, sa)
        # نمایه مکانی لایه دوم: مرتب‌سازی <-> در SRID خود آن
        ga_in_b = sql.SQL("ST_Transform({}, {})").format(ga, sql.Literal(sb)) if sb not in (0, 4326) else ga
        gb_raw = sql.SQL("n.{}").format(sql.Identifier(cb))
        gb = _geom4326("n", cb, sb)
        body = sql.SQL(
            "SELECT {attrs}{lbl} round(ST_Distance({ga}::geography, {gb}::geography)::numeric, 1) AS distance_m, "
            "{ga}::geometry AS geom FROM {A} a CROSS JOIN LATERAL (SELECT * FROM {B} n WHERE n.{cb} IS NOT NULL "
            "ORDER BY {gbr} <-> {gab} LIMIT 1) n WHERE a.{ca} IS NOT NULL").format(
            attrs=sql.SQL(", ").join(_attrs(ex, a, "a")) + sql.SQL(", ") if _attrs(ex, a, "a") else sql.SQL(""),
            lbl=sql.SQL("n.{} AS nearest_name,").format(sql.Identifier(label)) if label else sql.SQL(""),
            ga=ga, gb=gb, A=sql.Identifier(a.schema, a.name), B=sql.Identifier(b.schema, b.name),
            cb=sql.Identifier(cb), gbr=gb_raw, gab=ga_in_b, ca=sql.Identifier(ca))
    elif key == "count":
        p, q = table("layer"), table("other")
        cp, sp, _ = _geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = _geom_of(q)
        gq_in_p = _in_srid("q", cq, sq, sp)
        attrs = _attrs(ex, p, "p")
        extra = sql.SQL("")
        value = (params.get("value") or "").strip()
        if value:  # جمع یا میانگین یک ستون عددی لایه نقطه‌ای در هر چندضلعی
            agg = params.get("agg") if params.get("agg") in ("sum", "avg", "min", "max") else "sum"
            col_q = next((c for c in ex.columns(q) if c["name"] == value and not c["spatial"]), None)
            if col_q is None or col_q["base"] not in NUMERIC:
                raise ToolError("ستون مقدار باید یک ستون عددی در لایه نقطه‌ای باشد.")
            extra = sql.SQL(", {a}(q.{v}::float8) AS {n}").format(
                a=sql.SQL(agg), v=sql.Identifier(value), n=sql.Identifier(f"{agg}_{value}"[:63]))
        body = sql.SQL(
            "SELECT {attrs}c.point_count{extra_out}, {gp} AS geom FROM {P} p CROSS JOIN LATERAL "
            "(SELECT count(*) AS point_count{extra} FROM {Q} q WHERE ST_Intersects(p.{cp}, {gq})) c "
            "WHERE p.{cp} IS NOT NULL").format(
            attrs=sql.SQL(", ").join(attrs) + sql.SQL(", ") if attrs else sql.SQL(""), Q=sql.Identifier(q.schema, q.name),
            cp=sql.Identifier(cp), gq=gq_in_p, gp=_geom4326("p", cp, sp), P=sql.Identifier(p.schema, p.name),
            extra=extra, extra_out=sql.SQL(", c.{}").format(sql.Identifier(f"{agg}_{value}"[:63])) if value else sql.SQL(""))
    elif key == "overlap":
        p, q = table("layer"), table("other")
        cp, sp, _ = _geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = _geom_of(q, ("POLYGON",), ex)
        cat, zone = (params.get("category") or "").strip(), (params.get("zone") or "").strip()
        if cat not in {c["name"] for c in ex.columns(q) if not c["spatial"]}:
            raise ToolError("ستون دسته (مثلاً کاربری) را از لایه دوم انتخاب کنید.")
        if zone not in {c["name"] for c in ex.columns(p) if not c["spatial"]}:
            raise ToolError("ستون نام یا شناسه چندضلعی‌ها (مثلاً نام محله) را از لایه اول انتخاب کنید.")
        pz, qz = _geom4326("p", cp, sp), _geom4326("q", cq, sq)
        body = sql.SQL(
            "WITH j AS (SELECT p.ctid::text AS pid, p.{zone}::text AS zone, q.{cat}::text AS category, "
            "ST_Area(ST_MakeValid({pz})::geography) AS zone_area, i.g FROM {P} p JOIN {Q} q ON ST_Intersects(p.{cp}, {gq}) "
            "CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_Intersection(ST_MakeValid({pz}), ST_MakeValid({qz})), 3) AS g) i "
            "WHERE p.{cp} IS NOT NULL AND q.{cq} IS NOT NULL AND q.{cat} IS NOT NULL AND NOT ST_IsEmpty(i.g)) "
            "SELECT zone, category, round(sum(ST_Area(g::geography))::numeric, 1) AS area_m2, "
            "round((100 * sum(ST_Area(g::geography)) / NULLIF(max(zone_area), 0))::numeric, 2) AS share_pct, "
            "ST_Multi(ST_Union(g))::geometry(MultiPolygon, 4326) AS geom FROM j GROUP BY pid, zone, category").format(
            zone=sql.Identifier(zone), cat=sql.Identifier(cat), pz=pz, qz=qz, P=sql.Identifier(p.schema, p.name),
            Q=sql.Identifier(q.schema, q.name), cp=sql.Identifier(cp), cq=sql.Identifier(cq),
            gq=_in_srid("q", cq, sq, sp))
    elif key == "change":
        p, q = table("layer"), table("other")
        cp, sp, _ = _geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = _geom_of(q, ("POLYGON",), ex)
        cat, cat2 = (params.get("category") or "").strip(), (params.get("category2") or "").strip()
        if cat not in {c["name"] for c in ex.columns(p) if not c["spatial"]}:
            raise ToolError("ستون دسته‌ی نسخه‌ی قدیم (لایه اول) را انتخاب کنید.")
        if cat2 not in {c["name"] for c in ex.columns(q) if not c["spatial"]}:
            raise ToolError("ستون دسته‌ی نسخه‌ی جدید (لایه دوم) را انتخاب کنید.")
        pz, qz = _geom4326("p", cp, sp), _geom4326("q", cq, sq)
        body = sql.SQL(
            "WITH j AS (SELECT p.{cat}::text AS from_category, q.{cat2}::text AS to_category, i.g FROM {P} p "
            "JOIN {Q} q ON ST_Intersects(p.{cp}, {gq}) CROSS JOIN LATERAL (SELECT ST_CollectionExtract("
            "ST_Intersection(ST_MakeValid({pz}), ST_MakeValid({qz})), 3) AS g) i WHERE p.{cp} IS NOT NULL AND q.{cq} IS NOT NULL "
            "AND p.{cat} IS NOT NULL AND q.{cat2} IS NOT NULL AND NOT ST_IsEmpty(i.g)) "
            "SELECT from_category, to_category, round(sum(ST_Area(g::geography))::numeric, 1) AS area_m2, "
            "ST_Multi(ST_Union(g))::geometry(MultiPolygon, 4326) AS geom FROM j GROUP BY 1, 2").format(
            cat=sql.Identifier(cat), cat2=sql.Identifier(cat2), P=sql.Identifier(p.schema, p.name),
            Q=sql.Identifier(q.schema, q.name), cp=sql.Identifier(cp), cq=sql.Identifier(cq), pz=pz, qz=qz,
            gq=_in_srid("q", cq, sq, sp))
    elif key == "hexbin":
        t = table("layer")
        col, srid, _ = _geom_of(t)
        size = number("size", 20, 50_000)
        g3857 = sql.SQL("ST_Transform({}, 3857)").format(_geom4326("s", col, srid))
        body = sql.SQL(
            "WITH pts AS (SELECT {g} AS g FROM {src} s WHERE s.{c} IS NOT NULL), "
            "grid AS (SELECT h.geom FROM ST_HexagonGrid({size}, (SELECT ST_SetSRID(ST_Extent(g)::geometry, 3857) FROM pts)) h) "
            "SELECT count(*) AS count, ST_Transform(grid.geom, 4326)::geometry(Polygon, 4326) AS geom "
            "FROM grid JOIN pts ON ST_Intersects(grid.geom, pts.g) GROUP BY grid.geom").format(
            g=g3857, src=sql.Identifier(t.schema, t.name), c=sql.Identifier(col), size=sql.Literal(size))
    elif key in NEW_TOOLS:
        body = _prepare_new(key, params, ex, table, number, guard, need_routing)
    else:  # isochrone
        need_routing()
        lon, lat = number("lon", -180, 180), number("lat", -90, 90)
        dist = number("distance", 50, 50_000)
        body = sql.SQL(
            "WITH s AS (SELECT id FROM routing.ways_vertices_pgr "
            "ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326) LIMIT 1), "
            "d AS (SELECT * FROM pgr_drivingDistance('SELECT gid AS id, source, target, length_m AS cost, "
            "CASE WHEN reverse_cost < 0 THEN -1 ELSE length_m END AS reverse_cost FROM routing.ways', "
            "(SELECT id FROM s), {dist})), "
            "e AS (SELECT w.the_geom FROM routing.ways w JOIN d ON d.edge = w.gid) "
            "SELECT {dist}::int AS distance_m, count(*) AS edges, "
            "ST_Multi(ST_ConcaveHull(ST_Collect(e.the_geom), 0.3))::geometry(MultiPolygon, 4326) AS geom FROM e").format(
            lon=sql.Literal(lon), lat=sql.Literal(lat), dist=sql.Literal(dist))

    return ex, out, target, body, guards


NEW_TOOLS = {"within", "voronoi", "cluster", "measure", "clip", "erase", "route", "netnearest", "coverage"}
EDGES = ("'SELECT gid AS id, source, target, length_m AS cost, "
         "CASE WHEN reverse_cost < 0 THEN -1 ELSE length_m END AS reverse_cost FROM routing.ways'")
CAP_VORONOI, CAP_NET_FROM, CAP_NET_TO, CAP_COVERAGE = 5000, 3000, 500, 500


def _attr_sql(ex, t, alias: str):
    a = _attrs(ex, t, alias)
    return sql.SQL(", ").join(a) + sql.SQL(", ") if a else sql.SQL("")


def _nearest_vertex(lon, lat):
    return sql.SQL("ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint({}, {}), 4326) LIMIT 1").format(sql.Literal(lon), sql.Literal(lat))


def _bbox_pre(alias: str, col: str, srid: int, other):
    """شرط && روی نمایه مکانی (فقط وقتی SRID ستون روشن است)؛ خالی = بدون پیش‌فیلتر."""
    c = sql.SQL("{}.{}").format(sql.Identifier(alias), sql.Identifier(col))
    if srid == 4326:
        return sql.SQL("AND {} && {}").format(c, other)
    if srid > 0:
        return sql.SQL("AND {} && ST_Transform({}, {})").format(c, other, sql.Literal(srid))
    return sql.SQL("")


def _base_kinds(gtype: str) -> list[str]:
    return [k for k in ("POINT", "LINESTRING", "POLYGON") if k in gtype]


def _prepare_new(key, params, ex, table, number, guard, need_routing):
    """بدنه SELECT ابزارهای افزوده‌شده (فاصله، تیسن، خوشه، طول و مساحت، برش، حذف و سه ابزار شبکه)."""
    ident = sql.Identifier
    if key == "within":
        a, b = table("layer"), table("other")
        ca, sa, _ = _geom_of(a)
        cb, sb, _ = _geom_of(b)
        d = number("distance", 1, 100_000)
        ga, gb = _geom4326("a", ca, sa), _geom4326("b", cb, sb)
        pre = sql.SQL("")
        if sb in (0, 4326):  # پیش‌فیلتر جعبه‌ای با نمایه لایه دوم؛ درجه طول با کسینوس عرض بزرگ‌نمایی می‌شود
            pre = sql.SQL("AND b.{cb} && ST_Expand({ga}, {d} / (111320.0 * greatest(cos(radians(least(abs(ST_Y(ST_PointOnSurface({ga}))), "
                          "85))), 0.05)))").format(cb=ident(cb), ga=ga, d=sql.Literal(d))
        return sql.SQL(
            "SELECT {attrs}c.neighbor_count, {ga}::geometry AS geom FROM {A} a CROSS JOIN LATERAL (SELECT count(*) AS neighbor_count "
            "FROM {B} b WHERE b.{cb} IS NOT NULL {pre} AND ST_DWithin({ga}::geography, {gb}::geography, {d})) c "
            "WHERE a.{ca} IS NOT NULL AND c.neighbor_count > 0").format(
            attrs=_attr_sql(ex, a, "a"), ga=ga, gb=gb, A=ident(a.schema, a.name), B=ident(b.schema, b.name), ca=ident(ca),
            cb=ident(cb), pre=pre, d=sql.Literal(d))
    if key == "voronoi":
        p = table("layer")
        cp, sp, _ = _geom_of(p, ("POINT",), ex)
        guard(p, cp, CAP_VORONOI, f"حوزه نفوذ تا {CAP_VORONOI} نقطه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        clip_t = table("other") if params.get("other") else None
        mask, cell = sql.SQL(""), sql.SQL("cells.cell")
        if clip_t is not None:
            cq, sq, _ = _geom_of(clip_t, ("POLYGON",), ex)
            mask = sql.SQL(", mask AS (SELECT ST_Union(ST_MakeValid({g})) AS g FROM {Q} q WHERE q.{c} IS NOT NULL)").format(
                g=_geom4326("q", cq, sq), Q=ident(clip_t.schema, clip_t.name), c=ident(cq))
            cell = sql.SQL("ST_CollectionExtract(ST_Intersection(ST_MakeValid(cells.cell), mask.g), 3)")
        return sql.SQL(
            "WITH pts AS (SELECT {attrs}{g}::geometry AS g FROM {P} p WHERE p.{cp} IS NOT NULL), "
            "cells AS (SELECT (ST_Dump(ST_VoronoiPolygons((SELECT ST_Collect(g) FROM pts)))).geom AS cell){mask} "
            "SELECT {out_attrs}round(ST_Area(r.g::geography)::numeric, 1) AS area_m2, r.g AS geom FROM cells "
            "JOIN pts ON ST_Contains(cells.cell, pts.g) {mask_join}CROSS JOIN LATERAL (SELECT {cell} AS g) r "
            "WHERE NOT ST_IsEmpty(r.g)").format(
            attrs=_attr_sql(ex, p, "p"), g=_geom4326("p", cp, sp), P=ident(p.schema, p.name), cp=ident(cp), mask=mask,
            out_attrs=_attr_sql(ex, p, "pts"), cell=cell, mask_join=sql.SQL("CROSS JOIN mask ") if clip_t is not None else sql.SQL(""))
    if key == "cluster":
        p = table("layer")
        cp, sp, _ = _geom_of(p, ("POINT",), ex)
        eps, n = number("distance", 1, 100_000), int(number("minpoints", 2, 1000))
        return sql.SQL(
            "WITH pts AS (SELECT {g}::geometry AS g FROM {P} p WHERE p.{cp} IS NOT NULL), "
            "k AS (SELECT greatest(cos(radians(least(abs(avg(ST_Y(g))), 85))), 0.05) AS c FROM pts), "
            "cl AS (SELECT g, ST_ClusterDBSCAN(ST_Transform(g, 3857), eps := {eps} / (SELECT c FROM k), minpoints := {n}) OVER () AS cid "
            "FROM pts) "
            "SELECT (cid + 1)::int AS cluster_id, count(*) AS point_count, "
            "ST_Buffer(ST_ConvexHull(ST_Collect(g))::geography, least({eps} * 0.1, 50))::geometry(Polygon, 4326) AS geom "
            "FROM cl WHERE cid IS NOT NULL GROUP BY cid").format(
            g=_geom4326("p", cp, sp), P=ident(p.schema, p.name), cp=ident(cp), eps=sql.Literal(eps), n=sql.Literal(n))
    if key == "measure":
        p, q = table("layer"), table("other")
        mode = "area" if params.get("mode") == "area" else "length"
        cp, sp, _ = _geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = _geom_of(q, ("POLYGON",) if mode == "area" else ("LINE",), ex)
        pg, qg = _geom4326("p", cp, sp), _geom4326("q", cq, sq)
        inter = sql.SQL("ST_CollectionExtract(ST_Intersection(ST_MakeValid({pg}), ST_MakeValid({qg})), {k})").format(
            pg=pg, qg=qg, k=sql.Literal(3 if mode == "area" else 2))
        if mode == "area":
            val = sql.SQL("coalesce(ST_Area(ST_Union({i})::geography), 0)").format(i=inter)
            out = sql.SQL("round(m.v::numeric, 1) AS area_m2, round((100 * m.v / NULLIF(ST_Area({pg}::geography), 0))::numeric, 2) "
                          "AS share_pct").format(pg=pg)
        else:
            val = sql.SQL("coalesce(sum(ST_Length({i}::geography)), 0)").format(i=inter)
            out = sql.SQL("round(m.v::numeric, 1) AS length_m, round((m.v / 1000.0 / NULLIF(ST_Area({pg}::geography) / 1e6, 0))::numeric, 3) "
                          "AS km_per_km2").format(pg=pg)
        return sql.SQL(
            "SELECT {attrs}{out}, {pg} AS geom FROM {P} p CROSS JOIN LATERAL (SELECT {val} AS v FROM {Q} q "
            "WHERE q.{cq} IS NOT NULL AND ST_Intersects(p.{cp}, {gq})) m WHERE p.{cp} IS NOT NULL").format(
            attrs=_attr_sql(ex, p, "p"), out=out, pg=pg, val=val, P=ident(p.schema, p.name), Q=ident(q.schema, q.name),
            cp=ident(cp), cq=ident(cq), gq=_in_srid("q", cq, sq, sp))
    if key in ("clip", "erase"):
        a, q = table("layer"), table("other")
        ca, sa, ta = _geom_of(a, ("POLYGON",) if key == "erase" else ("POINT", "LINE", "POLYGON"), ex)
        cq, sq, _ = _geom_of(q, ("POLYGON",), ex)
        ga = _geom4326("a", ca, sa)
        mask = sql.SQL("WITH m AS (SELECT ST_Union(ST_MakeValid({g})) AS g FROM {Q} q WHERE q.{c} IS NOT NULL) ").format(
            g=_geom4326("q", cq, sq), Q=ident(q.schema, q.name), c=ident(cq))
        A = ident(a.schema, a.name)
        if key == "clip":
            kinds = _base_kinds(ta.upper())
            res = sql.SQL("ST_Intersection(ST_MakeValid({ga}), m.g)").format(ga=ga)
            if len(kinds) == 1:
                res = sql.SQL("ST_CollectionExtract({}, {})").format(res, sql.Literal({"POINT": 1, "LINESTRING": 2, "POLYGON": 3}[kinds[0]]))
            return mask + sql.SQL(
                "SELECT {attrs}c.g AS geom FROM {A} a CROSS JOIN m CROSS JOIN LATERAL (SELECT {res} AS g) c "
                "WHERE a.{ca} IS NOT NULL AND m.g IS NOT NULL {pre} AND ST_Intersects({ga}, m.g) AND NOT ST_IsEmpty(c.g)").format(
                attrs=_attr_sql(ex, a, "a"), A=A, res=res, ca=ident(ca), ga=ga, pre=_bbox_pre("a", ca, sa, sql.SQL("m.g")))
        res = sql.SQL("ST_CollectionExtract(CASE WHEN m.g IS NOT NULL AND ST_Intersects({ga}, m.g) "
                      "THEN ST_Difference(ST_MakeValid({ga}), m.g) ELSE ST_MakeValid({ga}) END, 3)").format(ga=ga)
        return mask + sql.SQL(
            "SELECT {attrs}round(ST_Area(c.g::geography)::numeric, 1) AS area_m2, c.g AS geom FROM {A} a CROSS JOIN m "
            "CROSS JOIN LATERAL (SELECT {res} AS g) c WHERE a.{ca} IS NOT NULL AND NOT ST_IsEmpty(c.g)").format(
            attrs=_attr_sql(ex, a, "a"), A=A, res=res, ca=ident(ca))
    # --- ابزارهای شبکه معابر ---
    need_routing()
    if key == "route":
        lon, lat, lon2, lat2 = number("lon", -180, 180), number("lat", -90, 90), number("lon2", -180, 180), number("lat2", -90, 90)
        return sql.SQL(
            "WITH s AS (SELECT id FROM routing.ways_vertices_pgr {s}), t AS (SELECT id FROM routing.ways_vertices_pgr {t}), "
            "r AS (SELECT * FROM pgr_dijkstra({edges}, (SELECT id FROM s), (SELECT id FROM t), true) WHERE edge > 0) "
            "SELECT round(sum(r.cost)::numeric, 1) AS distance_m, count(*) AS edges, "
            "ST_Multi(ST_LineMerge(ST_Collect(w.the_geom ORDER BY r.seq)))::geometry(MultiLineString, 4326) AS geom "
            "FROM r JOIN routing.ways w ON w.gid = r.edge HAVING count(*) > 0").format(
            s=_nearest_vertex(lon, lat), t=_nearest_vertex(lon2, lat2), edges=sql.SQL(EDGES))
    a = table("layer")
    ca, sa, _ = _geom_of(a, ("POINT",), ex)
    vertex = sql.SQL("CROSS JOIN LATERAL (SELECT id FROM routing.ways_vertices_pgr ORDER BY the_geom <-> {g} LIMIT 1) v").format(
        g=_geom4326("a", ca, sa))
    if key == "coverage":
        dist = number("distance", 50, 50_000)
        guard(a, ca, CAP_COVERAGE, f"پوشش چند مرکز تا {CAP_COVERAGE} نقطه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        return sql.SQL(
            "WITH o AS (SELECT {attrs}v.id AS vid FROM {A} a {vertex} WHERE a.{ca} IS NOT NULL), "
            "d AS (SELECT * FROM pgr_drivingDistance({edges}, (SELECT array_agg(DISTINCT vid) FROM o), {dist}, true, true)), "
            "h AS (SELECT d.start_vid, count(*) AS edges, ST_ConcaveHull(ST_Collect(w.the_geom), 0.3) AS hull "
            "FROM d JOIN routing.ways w ON w.gid = d.edge GROUP BY d.start_vid) "
            "SELECT {oattrs}{dist}::int AS distance_m, h.edges, CASE WHEN GeometryType(h.hull) = 'POLYGON' THEN h.hull "
            "ELSE ST_Buffer(h.hull::geography, 20)::geometry END AS geom FROM o JOIN h ON h.start_vid = o.vid").format(
            attrs=_attr_sql(ex, a, "a"), A=ident(a.schema, a.name), vertex=vertex, ca=ident(ca), edges=sql.SQL(EDGES),
            dist=sql.Literal(dist), oattrs=_attr_sql(ex, a, "o"))
    # netnearest
    b = table("other")
    cb, sb, _ = _geom_of(b, ("POINT",), ex)
    label = params.get("label") or ""
    if label and label not in _cols(ex, b):
        raise ToolError("ستون نام لایه دوم نامعتبر است.")
    dist = number("distance", 50, 50_000)
    guard(a, ca, CAP_NET_FROM, f"این ابزار تا {CAP_NET_FROM} نقطه مبدأ را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
    guard(b, cb, CAP_NET_TO, f"این ابزار تا {CAP_NET_TO} مرکز مقصد را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
    gb = _geom4326("b", cb, sb)
    lbl_t = sql.SQL(", b.{}::text AS lbl").format(ident(label)) if label else sql.SQL("")
    return sql.SQL(
        "WITH o AS (SELECT {attrs}{ga}::geometry AS g, v.id AS vid FROM {A} a {vertex} WHERE a.{ca} IS NOT NULL), "
        "t AS (SELECT DISTINCT ON (v.id) v.id AS vid{lbl_t} FROM {B} b CROSS JOIN LATERAL (SELECT id FROM routing.ways_vertices_pgr "
        "ORDER BY the_geom <-> {gb} LIMIT 1) v WHERE b.{cb} IS NOT NULL), "
        "near AS (SELECT DISTINCT ON (start_vid) start_vid, end_vid, dist FROM ("
        "SELECT start_vid, end_vid, max(agg_cost) AS dist FROM pgr_dijkstraNear({edges}, "
        "(SELECT array_agg(DISTINCT vid) FROM o), (SELECT array_agg(vid) FROM t), directed := true, cap := 1, global := false) "
        "GROUP BY start_vid, end_vid "
        "UNION ALL SELECT o2.vid, t.vid, 0 FROM (SELECT DISTINCT vid FROM o) o2 JOIN t ON t.vid = o2.vid) u "
        "ORDER BY start_vid, dist) "
        "SELECT {oattrs}round(n.dist::numeric, 1) AS network_m{lbl_out}, o.g AS geom FROM o "
        "LEFT JOIN near n ON n.start_vid = o.vid AND n.dist <= {dist} LEFT JOIN t ON t.vid = n.end_vid").format(
        attrs=_attr_sql(ex, a, "a"), ga=_geom4326("a", ca, sa), A=ident(a.schema, a.name), vertex=vertex, ca=ident(ca),
        lbl_t=lbl_t, B=ident(b.schema, b.name), gb=gb, cb=ident(cb), edges=sql.SQL(EDGES), oattrs=_attr_sql(ex, a, "o"),
        lbl_out=sql.SQL(", t.lbl AS nearest_name") if label else sql.SQL(""), dist=sql.Literal(dist))



def validate(db, key: str, params: dict) -> str:
    """همان بررسی‌های اجرا، بدون اجرا؛ نام جدول خروجی را برمی‌گرداند."""
    return _prepare(db, key, params)[1]


def summarize(db, key: str, params: dict) -> str:
    """توضیح کوتاه فارسی از ورودی‌ها برای ردیف تاریخچه."""
    parts = []
    if params.get("layer"):
        parts.append(params["layer"].removeprefix("public."))
    if params.get("other"):
        parts.append("با " + params["other"].removeprefix("public."))
    for k, label, unit in (("distance", "فاصله", "متر"), ("size", "اندازه خانه", "متر")):
        if params.get(k):
            parts.append(f"{label} {params[k]} {unit}")
    if key in ("isochrone", "route") and params.get("lon"):
        parts.append(f"از {params.get('lon')}, {params.get('lat')}")
    if key == "route" and params.get("lon2"):
        parts.append(f"تا {params.get('lon2')}, {params.get('lat2')}")
    if key == "cluster" and params.get("minpoints"):
        parts.append(f"حداقل {params['minpoints']} نقطه")
    if key == "measure":
        parts.append("مساحت" if params.get("mode") == "area" else "طول")
    if params.get("value"):
        parts.append(f"{params.get('agg') or 'sum'} {params['value']}")
    if params.get("category"):
        parts.append(f"دسته {params['category']}" + (f" ← {params['category2']}" if params.get("category2") else ""))
    if params.get("dissolve") == "on":
        parts.append("یکپارچه")
    return " · ".join(parts)[:300]


PUBLIC_PARAMS = ("layer", "other", "label", "distance", "size", "lon", "lat", "dissolve", "output", "replace", "value", "agg",
                 "category", "zone", "category2", "lon2", "lat2", "minpoints", "mode")


def run_job(job) -> dict:
    """اجرا در کارگر؛ پارامترها از ToolRun خوانده می‌شود."""
    run_ = job.tool_run
    return run(job.database, run_.tool, run_.params, job=job, run_row=run_)


def run(db, key: str, params: dict, job=None, run_row=None) -> dict:
    def step(pct: int, text: str):
        if job is not None:
            job.set_progress(pct, text)

    step(5, "بررسی ورودی‌ها")
    ex, out, target, body, guards = _prepare(db, key, params)
    step(12, "ساخت جدول نتیجه (سنگین‌ترین مرحله)")
    from databases.provisioner import Provisioner

    try:
        with ex.connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
            conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(TIMEOUT)))
            for q, cap, msg in guards:
                if conn.execute(q).fetchone()[0] > cap:
                    raise ToolError(msg)
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(target))
            conn.execute(sql.SQL("CREATE TABLE {} AS {}").format(target, body))
            if key == "route" and conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0] == 0:
                raise ToolError("مسیری بین این دو نقطه روی شبکه معابر پیدا نشد (شاید در دو بخش جدا از هم هستند).")
            step(65, "تنظیم نوع هندسه و سیستم مختصات")
            _fix_geom_type(conn, target)
            step(78, "افزودن کلید اصلی")
            conn.execute(sql.SQL("ALTER TABLE {} ADD COLUMN gid serial PRIMARY KEY").format(target))
            step(86, "ساخت نمایه مکانی")
            conn.execute(sql.SQL("CREATE INDEX ON {} USING gist (geom)").format(target))
            step(94, "آماده‌سازی نهایی")
            conn.execute(sql.SQL("ANALYZE {}").format(target))
            n = conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0]
            conn.commit()
    except ExplorerError as exc:
        raise ToolError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001  خطای PostgreSQL (مثلاً timeout)
        msg = str(exc).splitlines()[0]
        if "statement timeout" in msg:
            msg = "تحلیل بیش از ۳ دقیقه طول کشید؛ داده را کوچک‌تر کنید یا پارامتر را تغییر دهید."
        raise ToolError(f"تحلیل انجام نشد: {msg}") from exc
    Provisioner.for_server(db.server).reassign_browser_objects(db.db_name, db.role_name)
    if run_row is not None:
        run_row.rows = n
        run_row.save(update_fields=["rows"])
    return {"table": out, "rows": n}
