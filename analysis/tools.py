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
    else:  # isochrone
        if "routing.ways" not in tables:
            raise ToolError("شبکه معابر (routing.ways) ندارید؛ از «داده آماده ایران» شبکه مسیریابی بگیرید.")
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

    return ex, out, target, body


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
    if key == "isochrone" and params.get("lon"):
        parts.append(f"نقطه {params.get('lon')}, {params.get('lat')}")
    if params.get("value"):
        parts.append(f"{params.get('agg') or 'sum'} {params['value']}")
    if params.get("category"):
        parts.append(f"دسته {params['category']}" + (f" ← {params['category2']}" if params.get("category2") else ""))
    if params.get("dissolve") == "on":
        parts.append("یکپارچه")
    return " · ".join(parts)[:300]


PUBLIC_PARAMS = ("layer", "other", "label", "distance", "size", "lon", "lat", "dissolve", "output", "replace", "value", "agg",
                 "category", "zone", "category2")


def run_job(job) -> dict:
    """اجرا در کارگر؛ پارامترها از ToolRun خوانده می‌شود."""
    run_ = job.tool_run
    return run(job.database, run_.tool, run_.params, job=job, run_row=run_)


def run(db, key: str, params: dict, job=None, run_row=None) -> dict:
    def step(pct: int, text: str):
        if job is not None:
            job.set_progress(pct, text)

    step(5, "بررسی ورودی‌ها")
    ex, out, target, body = _prepare(db, key, params)
    step(12, "ساخت جدول نتیجه (سنگین‌ترین مرحله)")
    from databases.provisioner import Provisioner

    try:
        with ex.connect(read_only=False) as conn:
            conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
            conn.execute(sql.SQL("SET statement_timeout = {}").format(sql.Literal(TIMEOUT)))
            conn.execute(sql.SQL("DROP TABLE IF EXISTS {}").format(target))
            conn.execute(sql.SQL("CREATE TABLE {} AS {}").format(target, body))
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
