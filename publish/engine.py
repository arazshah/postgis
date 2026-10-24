"""ساخت کاشی برداری و عوارض GeoJSON مستقیم در PostGIS (ST_AsMVT / ST_AsGeoJSON) با نقش مرورگر کاربر."""
from __future__ import annotations

import json
import threading
import time
from contextlib import ExitStack, contextmanager

import psycopg
from psycopg import sql

from databases.explorer import Explorer, ExplorerError

MVT_TYPES = {"int2", "int4", "int8", "float4", "float8", "bool", "text", "varchar", "bpchar", "name"}
NUMERIC_TYPES = {"int2", "int4", "int8", "float4", "float8", "numeric"}
TILE_FEATURE_LIMIT = 100_000
MAX_ITEMS = 5000


class EngineError(Exception):
    pass


# نقش مرورگر (_web) حداکثر ۳ اتصال دارد و نقشه چند کاشی را هم‌زمان می‌خواهد:
# در هر پروسه حداکثر ۲ اتصال هم‌زمان برای هر پایگاه داده، و اگر پروسه‌های دیگر
# سقف را پر کرده بودند، چند بار با فاصله کوتاه دوباره تلاش می‌کنیم.
PER_DB_CONCURRENCY = 2
_RETRY_DELAYS = (0.05, 0.1, 0.2, 0.4, 0.8)
_slots: dict[int, threading.BoundedSemaphore] = {}
_slots_lock = threading.Lock()


def _slot(db_id: int) -> threading.BoundedSemaphore:
    with _slots_lock:
        if db_id not in _slots:
            _slots[db_id] = threading.BoundedSemaphore(PER_DB_CONCURRENCY)
        return _slots[db_id]


@contextmanager
def _connect(layer):
    db = layer.database
    slot = _slot(db.pk)
    if not slot.acquire(timeout=20):
        raise ExplorerError("سرور مشغول است؛ چند لحظه بعد دوباره تلاش کنید.")
    try:
        with ExitStack() as stack:
            for delay in (*_RETRY_DELAYS, None):
                try:
                    conn = stack.enter_context(Explorer(db).connect())
                    break
                except ExplorerError as exc:
                    if delay is None or "too many connections" not in str(exc):
                        raise
                    time.sleep(delay)
            yield conn
    finally:
        slot.release()


def table_meta(conn, schema: str, table: str) -> dict:
    """ستون‌ها (نام و نوع) و کلید اصلی تک‌ستونی جدول."""
    oid = conn.execute("SELECT to_regclass(%s)", (sql.Identifier(schema, table).as_string(conn),)).fetchone()[0]
    if oid is None:
        raise EngineError("جدول پیدا نشد.")
    cols = conn.execute("""
        SELECT a.attname, t.typname FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum
    """, (oid,)).fetchall()
    pk = conn.execute("""
        SELECT array_agg(a.attname) FROM pg_index i JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary
    """, (oid,)).fetchone()[0] or []
    return {"columns": [(n, t) for n, t in cols], "pk": pk[0] if len(pk) == 1 else ""}


def _props(layer, columns: list[tuple[str, str]], for_mvt: bool) -> list[tuple[str, sql.Composable]]:
    wanted = set(layer.columns or [])
    out = []
    for name, typ in columns:
        if name == layer.geom_column or typ in ("geometry", "geography", "raster", "bytea"):
            continue
        if wanted and name not in wanted:
            continue
        ident = sql.Identifier(name)
        if for_mvt and typ not in MVT_TYPES:
            expr = sql.SQL("{}::float8").format(ident) if typ == "numeric" else sql.SQL("{}::text").format(ident)
        else:
            expr = ident
        out.append((name, expr))
    return out


FAR_DOT_UNITS = 24   # کوچک‌تر از این (واحد کاشی ۴۰۹۶، حدود ۱٫۵ پیکسل) در زوم دور به نقطه تبدیل می‌شود
FAR_DOT_MAX_ZOOM = 14


def _far_dots(layer, z: int) -> bool:
    """چندضلعی و خط ریز در زوم دور به‌صورت نقطه فرستاده می‌شود، مگر سبک لایه آن را خاموش کرده باشد."""
    if z > FAR_DOT_MAX_ZOOM or "POINT" in (getattr(layer, "geom_type", "") or "").upper():
        return False
    style = getattr(layer, "style", None)
    return not (isinstance(style, dict) and style.get("far_dots") is False)


def tile(layer, z: int, x: int, y: int) -> bytes:
    if not (0 <= z <= 24 and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        raise EngineError("مختصات کاشی نامعتبر است.")
    with _connect(layer) as conn:
        meta = table_meta(conn, layer.schema, layer.table)
        props = _props(layer, meta["columns"], for_mvt=True)
        g = sql.Identifier(layer.geom_column)
        env = sql.SQL("ST_TileEnvelope({}, {}, {}, margin => (64.0 / 4096))").format(
            sql.Literal(z), sql.Literal(x), sql.Literal(y))
        filt = env if layer.srid == 3857 else sql.SQL("ST_Transform({}, {})").format(env, sql.Literal(layer.srid))
        geom3857 = g if layer.srid == 3857 else sql.SQL("ST_Transform({}, 3857)").format(g)
        cols = sql.SQL("").join(sql.SQL(", {} AS {}").format(e, sql.Identifier(n)) for n, e in props)
        shape, src = geom3857, None
        if _far_dots(layer, z):
            # عارضه‌ای که در این زوم از چند پیکسل کوچک‌تر است در کاشی حذف می‌شد؛ به‌جایش یک نقطه می‌فرستیم
            # تا لایه در زوم دور هم دیده شود (لایه نقطه‌ای کشیده می‌شود، همان رنگ و اندازه)
            unit = 40075016.68 / (2 ** z) / 4096
            thr = sql.Literal(unit * FAR_DOT_UNITS)
            shape = sql.SQL("CASE WHEN ST_XMax(__g) - ST_XMin(__g) < {t} AND ST_YMax(__g) - ST_YMin(__g) < {t}"
                            " THEN ST_PointOnSurface(__g) ELSE __g END").format(t=thr)
            src = sql.SQL(", LATERAL (SELECT {} AS __g) __q").format(geom3857)
        query = sql.SQL("""
            WITH mvt AS (
              SELECT ST_AsMVTGeom({geom}, ST_TileEnvelope({z}, {x}, {y}), 4096, 64, true) AS __geom{cols}
              FROM {rel}{src} WHERE {g} && {filt} LIMIT {lim}
            )
            SELECT ST_AsMVT(mvt.*, {name}, 4096, '__geom') FROM mvt WHERE __geom IS NOT NULL
        """).format(geom=shape, z=sql.Literal(z), x=sql.Literal(x), y=sql.Literal(y), cols=cols,
                    rel=sql.Identifier(layer.schema, layer.table), src=src or sql.SQL(""), g=g, filt=filt,
                    lim=sql.Literal(TILE_FEATURE_LIMIT), name=sql.Literal(layer.collection_id))
        try:
            data = conn.execute(query).fetchone()[0]
        except psycopg.Error as exc:
            raise EngineError(getattr(exc.diag, "message_primary", None) or str(exc)) from exc
        return bytes(data or b"")


BIG_TABLE = 1_000_000  # بیشتر از این تعداد ردیف: اول محدوده تخمینی آمار (سریع)، بعد دقیق


def extent(layer) -> list[float]:
    """محدوده لایه به طول و عرض جغرافیایی؛ برای جدول خیلی بزرگ ST_EstimatedExtent و اگر آمار نبود ST_Extent."""
    with _connect(layer) as conn:
        g = sql.Identifier(layer.geom_column)
        row = None
        reltuples = conn.execute(
            "SELECT c.reltuples FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE n.nspname = %s AND c.relname = %s", (layer.schema, layer.table)).fetchone()
        if reltuples and reltuples[0] > BIG_TABLE:
            try:
                with conn.transaction():  # نقطه‌ذخیره: خطای آمار نباید پرسمان بعدی را خراب کند
                    row = conn.execute(
                        "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM ("
                        "SELECT ST_Transform(ST_SetSRID(ST_EstimatedExtent(%s, %s, %s)::geometry, %s), 4326) AS e) s",
                        (layer.schema, layer.table, layer.geom_column, layer.srid)).fetchone()
            except psycopg.Error:
                row = None
        if not row or row[0] is None:
            row = conn.execute(sql.SQL(
                "SELECT ST_XMin(e), ST_YMin(e), ST_XMax(e), ST_YMax(e) FROM ("
                "SELECT ST_Transform(ST_SetSRID(ST_Extent({}), {}), 4326) AS e FROM {}) s").format(
                g, sql.Literal(layer.srid), sql.Identifier(layer.schema, layer.table))).fetchone()
    return [round(v, 6) for v in row] if row and row[0] is not None else []


def features(layer, *, bbox=None, limit=100, offset=0, filters=None, fid=None) -> dict:
    """GeoJSON با مختصات طول و عرض (CRS84)."""
    limit = max(1, min(int(limit), MAX_ITEMS))
    offset = max(0, int(offset))
    with _connect(layer) as conn:
        meta = table_meta(conn, layer.schema, layer.table)
        props = _props(layer, meta["columns"], for_mvt=False)
        allowed = {n for n, _ in props}
        pk = meta["pk"]
        g = sql.Identifier(layer.geom_column)
        where = [sql.SQL("{} IS NOT NULL").format(g)]
        params: list = []
        if bbox:
            where.append(sql.SQL("{} && ST_Transform(ST_MakeEnvelope(%s, %s, %s, %s, 4326), {})").format(
                g, sql.Literal(layer.srid)))
            params += list(bbox)
        for name, value in (filters or {}).items():
            if name in allowed:
                where.append(sql.SQL("{}::text = %s").format(sql.Identifier(name)))
                params.append(value)
        if fid is not None:
            if not pk:
                raise EngineError("این لایه کلید اصلی ندارد.")
            where.append(sql.SQL("{}::text = %s").format(sql.Identifier(pk)))
            params.append(str(fid))
        prop_obj = sql.SQL("json_build_object({})").format(
            sql.SQL(", ").join(sql.SQL("{}, {}").format(sql.Literal(n), e) for n, e in props)) if props \
            else sql.SQL("'{}'::json")
        idexpr = sql.SQL("{}").format(sql.Identifier(pk)) if pk else sql.SQL("NULL")
        geom4326 = g if layer.srid == 4326 else sql.SQL("ST_Transform({}, 4326)").format(g)
        query = sql.SQL("""
            SELECT json_build_object('type', 'Feature', 'id', {id}, 'geometry', ST_AsGeoJSON({geom}, 7)::json,
                                     'properties', {props})::text
            FROM {rel} WHERE {where} ORDER BY {order} LIMIT {lim} OFFSET {off}
        """).format(id=idexpr, geom=geom4326, props=prop_obj, rel=sql.Identifier(layer.schema, layer.table),
                    where=sql.SQL(" AND ").join(where), order=sql.Identifier(pk) if pk else sql.SQL("ctid"),
                    lim=sql.Literal(limit), off=sql.Literal(offset))
        try:
            rows = conn.execute(query, params).fetchall()
        except psycopg.Error as exc:
            raise EngineError(getattr(exc.diag, "message_primary", None) or str(exc)) from exc
    feats = [json.loads(r[0]) for r in rows]
    return {"type": "FeatureCollection", "features": feats, "numberReturned": len(feats)}


def describe(layer) -> dict:
    """ستون‌ها و کلید اصلی برای فرم انتشار و queryables."""
    try:
        with _connect(layer) as conn:
            return table_meta(conn, layer.schema, layer.table)
    except ExplorerError as exc:
        raise EngineError(str(exc)) from exc


def field_stats(layer, field: str, mode: str, classes: int = 5) -> dict:
    """برای سبک نقشه: مرزهای طبقه‌ها (چندک) برای ستون عددی، یا مقدارهای پرتکرار برای ستون متنی."""
    with _connect(layer) as conn:
        meta = table_meta(conn, layer.schema, layer.table)
        types = dict(meta["columns"])
        if field not in types or field == layer.geom_column:
            raise EngineError("ستون پیدا نشد.")
        col = sql.Identifier(field)
        rel = sql.Identifier(layer.schema, layer.table)
        if mode == "graduated":
            if types[field] not in NUMERIC_TYPES:
                raise EngineError("برای طبقه‌بندی عددی یک ستون عددی انتخاب کنید.")
            classes = max(2, min(int(classes), 9))
            qs = [round(i / classes, 4) for i in range(1, classes)]
            row = conn.execute(sql.SQL(
                "SELECT min({c})::float8, max({c})::float8, "
                "percentile_cont(%s::float8[]) WITHIN GROUP (ORDER BY {c}::float8) FROM {r} WHERE {c} IS NOT NULL"
            ).format(c=col, r=rel), (qs,)).fetchone()
            breaks = sorted({round(float(b), 6) for b in (row[2] or [])})
            return {"min": row[0], "max": row[1], "breaks": breaks}
        rows = conn.execute(sql.SQL(
            "SELECT {c}::text, count(*) FROM {r} WHERE {c} IS NOT NULL GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 12"
        ).format(c=col, r=rel)).fetchall()
        return {"values": [r[0] for r in rows], "counts": [r[1] for r in rows]}


def field_names(layer) -> list[tuple[str, str]]:
    meta = describe(layer)
    wanted = set(layer.columns or [])
    return [(n, t) for n, t in meta["columns"]
            if n != layer.geom_column and t not in ("geometry", "geography", "raster", "bytea")
            and (not wanted or n in wanted)]
