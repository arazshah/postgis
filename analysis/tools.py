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
        gq_in_p = sql.SQL("ST_Transform(q.{}, {})").format(sql.Identifier(cq), sql.Literal(sp)) \
            if sp != sq and sp not in (0,) and sq not in (0,) else sql.SQL("q.{}").format(sql.Identifier(cq))
        attrs = _attrs(ex, p, "p")
        body = sql.SQL(
            "SELECT {attrs}(SELECT count(*) FROM {Q} q WHERE ST_Intersects(p.{cp}, {gq})) AS point_count, "
            "{gp} AS geom FROM {P} p WHERE p.{cp} IS NOT NULL").format(
            attrs=sql.SQL(", ").join(attrs) + sql.SQL(", ") if attrs else sql.SQL(""), Q=sql.Identifier(q.schema, q.name),
            cp=sql.Identifier(cp), gq=gq_in_p, gp=_geom4326("p", cp, sp), P=sql.Identifier(p.schema, p.name))
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
    if params.get("dissolve") == "on":
        parts.append("یکپارچه")
    return " · ".join(parts)[:300]


PUBLIC_PARAMS = ("layer", "other", "label", "distance", "size", "lon", "lat", "dissolve", "output", "replace")


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
