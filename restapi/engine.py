"""
اجرای عملیات REST روی جدول کاربر: فهرست با فیلتر، خواندن، افزودن، ویرایش و حذف سطر.

نام ستون‌ها فقط از کاتالوگ خود PostgreSQL پذیرفته می‌شوند و مقدارها همیشه پارامتری‌اند. نوشتن با نقش خود
کاربر (SET ROLE) انجام می‌شود تا محدودیت‌ها و مالکیت درست بماند. هندسه ورودی و خروجی GeoJSON در WGS84 است.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from decimal import Decimal

from psycopg import sql

from databases.explorer import Explorer, ExplorerError

MAX_LIMIT = 1000
DEFAULT_LIMIT = 100
OPS = {"": "=", "gt": ">", "gte": ">=", "lt": "<", "lte": "<=", "ne": "<>", "like": "ILIKE"}


class RestError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


@contextmanager
def _conn(db, write: bool):
    try:
        with Explorer(db).connect(read_only=not write) as conn:
            if write:
                conn.execute(sql.SQL("SET ROLE {}").format(sql.Identifier(db.role_name)))
            yield conn
    except ExplorerError as exc:
        raise RestError(str(exc), 503) from exc


def meta(conn, schema: str, table: str) -> dict:
    oid = conn.execute("SELECT to_regclass(%s)", (sql.Identifier(schema, table).as_string(conn),)).fetchone()[0]
    if oid is None:
        raise RestError("جدول پیدا نشد.", 404)
    cols = conn.execute("""
        SELECT a.attname, format_type(a.atttypid, a.atttypmod), t.typname, NOT a.attnotnull,
               a.atthasdef OR a.attidentity <> '' OR a.attgenerated <> '', a.atttypmod
        FROM pg_attribute a JOIN pg_type t ON t.oid = a.atttypid
        WHERE a.attrelid = %s::regclass AND a.attnum > 0 AND NOT a.attisdropped ORDER BY a.attnum""",
        (oid,)).fetchall()
    pk = conn.execute("""
        SELECT array_agg(a.attname) FROM pg_index i JOIN pg_attribute a
          ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
        WHERE i.indrelid = %s::regclass AND i.indisprimary""", (oid,)).fetchone()[0] or []
    columns = [{"name": n, "type": f, "base": b, "nullable": nl, "default": d, "srid": 0, "_mod": mod}
               for n, f, b, nl, d, mod in cols]
    geoms = [c for c in columns if c["base"] in ("geometry", "geography")]
    for c in geoms:  # فقط وقتی PostGIS هست
        c["srid"] = conn.execute("SELECT postgis_typmod_srid(%s)", (c["_mod"],)).fetchone()[0] or 0
    if geoms and not geoms[0]["srid"]:
        srid = conn.execute(sql.SQL("SELECT ST_SRID({}) FROM {} WHERE {} IS NOT NULL LIMIT 1").format(
            sql.Identifier(geoms[0]["name"]), sql.Identifier(schema, table), sql.Identifier(geoms[0]["name"]))).fetchone()
        geoms[0]["srid"] = srid[0] if srid else 4326
    return {"columns": columns, "pk": pk[0] if len(pk) == 1 else "", "geom": geoms[0] if geoms else None}


def describe(db, schema: str, table: str) -> dict:
    with _conn(db, False) as conn:
        return meta(conn, schema, table)


def _select(m: dict):
    parts = []
    for c in m["columns"]:
        ident = sql.Identifier(c["name"])
        if c is m["geom"]:
            continue
        if c["base"] in ("bytea", "raster"):
            continue
        parts.append(ident)
    if m["geom"]:
        g = sql.Identifier(m["geom"]["name"])
        expr = sql.SQL("ST_AsGeoJSON(CASE WHEN ST_SRID({g}::geometry) IN (0, 4326) THEN {g}::geometry "
                       "ELSE ST_Transform({g}::geometry, 4326) END, 7)::json AS __geometry").format(g=g)
        parts.append(expr)
    return sql.SQL(", ").join(parts)


def _value(c: dict, v):
    """(بیان SQL، پارامتر) برای یک ستون؛ نوع از کاتالوگ."""
    if v is None:
        return sql.SQL("NULL"), None
    if c["base"] in ("geometry", "geography"):
        gj = json.dumps(v) if isinstance(v, dict) else str(v)
        expr = sql.SQL("ST_SetSRID(ST_GeomFromGeoJSON(%s), 4326)")
        if c["srid"] not in (0, 4326):
            expr = sql.SQL("ST_Transform({}, {})").format(expr, sql.Literal(int(c["srid"])))
        if c["base"] == "geography":
            expr = sql.SQL("{}::geography").format(expr)
        # ستون Multi* با ورودی ساده (مثلاً Point در MultiPoint)
        if "multi" in c["type"].lower():
            expr = sql.SQL("ST_Multi({})").format(expr)
        return expr, gj
    if isinstance(v, (dict, list)):
        v = json.dumps(v, ensure_ascii=False)
    return sql.SQL("CAST(%s AS {})").format(sql.SQL(c["type"])), v


def _row_out(m: dict, cols: list[str], row) -> dict:
    data = dict(zip(cols, row, strict=True))
    geom = data.pop("__geometry", None)
    for k, v in list(data.items()):
        if isinstance(v, Decimal):
            data[k] = int(v) if v == v.to_integral_value() else float(v)
        elif v is not None and not isinstance(v, (str, int, float, bool, list, dict)):
            data[k] = str(v)
    if m["geom"]:
        return {"type": "Feature", "id": data.get(m["pk"]) if m["pk"] else None, "geometry": geom, "properties": data}
    return data


def _body_values(m: dict, body: dict, require_all: bool) -> dict:
    if not isinstance(body, dict):
        raise RestError("بدنه درخواست باید یک شیء JSON باشد.")
    values = dict(body.get("properties") or {}) if body.get("type") == "Feature" else dict(body)
    if body.get("type") == "Feature" or "geometry" in body:
        geom = body.get("geometry")
        values.pop("geometry", None)
        values.pop("type", None)
        if m["geom"]:
            values[m["geom"]["name"]] = geom
    byname = {c["name"]: c for c in m["columns"]}
    unknown = [k for k in values if k not in byname]
    if unknown:
        raise RestError(f"ستون ناشناخته: {', '.join(unknown)[:200]}")
    if require_all:
        missing = [c["name"] for c in m["columns"] if not c["nullable"] and not c["default"] and c["name"] not in values]
        if missing:
            raise RestError(f"این ستون‌ها لازم‌اند: {', '.join(missing)}")
    if not values:
        raise RestError("هیچ ستونی برای ذخیره فرستاده نشده است.")
    return values


def _where(m, schema, table, filters: dict, bbox):
    conds, params = [], []
    byname = {c["name"]: c for c in m["columns"]}
    for key, raw in filters.items():
        name, _, op = key.partition("__")
        c = byname.get(name)
        if c is None or c is m["geom"]:
            raise RestError(f"فیلتر نامعتبر: {key}")
        if op == "in":
            items = [x for x in str(raw).split(",")][:100]
            conds.append(sql.SQL("{} = ANY(CAST(%s AS text[]))").format(sql.SQL("{}::text").format(sql.Identifier(name))))
            params.append(items)
            continue
        if op == "null":
            conds.append(sql.SQL("{} IS {}NULL").format(sql.Identifier(name),
                                                       sql.SQL("" if str(raw).lower() in ("1", "true") else "NOT ")))
            continue
        if op not in OPS:
            raise RestError(f"عملگر نامعتبر: {op}")
        if op == "like":
            conds.append(sql.SQL("{}::text ILIKE %s").format(sql.Identifier(name)))
            params.append(str(raw).replace("*", "%"))
        else:
            conds.append(sql.SQL("{} {} CAST(%s AS {})").format(sql.Identifier(name), sql.SQL(OPS[op]), sql.SQL(c["type"])))
            params.append(raw)
    if bbox:
        if not m["geom"]:
            raise RestError("این جدول هندسه ندارد.")
        g = sql.Identifier(m["geom"]["name"])
        env = sql.SQL("ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
        if m["geom"]["srid"] not in (0, 4326):
            env = sql.SQL("ST_Transform({}, {})").format(env, sql.Literal(int(m["geom"]["srid"])))
        conds.append(sql.SQL("{}::geometry && {}").format(g, env))
        params += list(bbox)
    return (sql.SQL(" WHERE ") + sql.SQL(" AND ").join(conds)) if conds else sql.SQL(""), params


def list_rows(db, schema, table, *, filters=None, bbox=None, order="", limit=DEFAULT_LIMIT, offset=0) -> dict:
    limit = max(1, min(int(limit), MAX_LIMIT))
    offset = max(0, int(offset))
    with _conn(db, False) as conn:
        m = meta(conn, schema, table)
        where, params = _where(m, schema, table, filters or {}, bbox)
        order_sql = sql.SQL("")
        if order:
            name = order.lstrip("-")
            if name not in {c["name"] for c in m["columns"]} or (m["geom"] and name == m["geom"]["name"]):
                raise RestError(f"مرتب‌سازی نامعتبر: {order}")
            order_sql = sql.SQL(" ORDER BY {} {}").format(sql.Identifier(name),
                                                         sql.SQL("DESC" if order.startswith("-") else "ASC"))
        elif m["pk"]:
            order_sql = sql.SQL(" ORDER BY {}").format(sql.Identifier(m["pk"]))
        q = sql.SQL("SELECT {} FROM {}{}{} LIMIT {} OFFSET {}").format(
            _select(m), sql.Identifier(schema, table), where, order_sql, sql.Literal(limit), sql.Literal(offset))
        cur = conn.execute(q, params)
        cols = [d.name for d in cur.description]
        rows = [_row_out(m, cols, r) for r in cur.fetchall()]
    if m["geom"]:
        return {"type": "FeatureCollection", "features": rows, "numberReturned": len(rows), "offset": offset}
    return {"rows": rows, "numberReturned": len(rows), "offset": offset}


def _need_pk(m):
    if not m["pk"]:
        raise RestError("این جدول کلید اصلی تک‌ستونی ندارد؛ از «سلامت داده» کلید اصلی بسازید.")


def get_row(db, schema, table, pk_value) -> dict:
    with _conn(db, False) as conn:
        m = meta(conn, schema, table)
        _need_pk(m)
        pkc = next(c for c in m["columns"] if c["name"] == m["pk"])
        cur = conn.execute(sql.SQL("SELECT {} FROM {} WHERE {} = CAST(%s AS {})").format(
            _select(m), sql.Identifier(schema, table), sql.Identifier(m["pk"]), sql.SQL(pkc["type"])), [pk_value])
        row = cur.fetchone()
        if row is None:
            raise RestError("سطر پیدا نشد.", 404)
        return _row_out(m, [d.name for d in cur.description], row)


def _exec_write(conn, q, params):
    try:
        cur = conn.execute(q, params)
    except Exception as exc:  # noqa: BLE001  خطای داده (نوع، محدودیت، هندسه)
        conn.rollback()
        msg = str(exc).splitlines()[0]
        raise RestError(f"ذخیره نشد: {msg[:300]}") from exc
    return cur


def insert(db, schema, table, body: dict) -> dict:
    with _conn(db, True) as conn:
        m = meta(conn, schema, table)
        values = _body_values(m, body, require_all=True)
        byname = {c["name"]: c for c in m["columns"]}
        exprs, params = [], []
        for k, v in values.items():
            e, p = _value(byname[k], v)
            exprs.append(e)
            if p is not None:
                params.append(p)
        q = sql.SQL("INSERT INTO {} ({}) VALUES ({}) RETURNING {}").format(
            sql.Identifier(schema, table), sql.SQL(", ").join(sql.Identifier(k) for k in values),
            sql.SQL(", ").join(exprs), _select(m))
        cur = _exec_write(conn, q, params)
        row = _row_out(m, [d.name for d in cur.description], cur.fetchone())
        conn.commit()
        return row


def update(db, schema, table, pk_value, body: dict) -> dict:
    with _conn(db, True) as conn:
        m = meta(conn, schema, table)
        _need_pk(m)
        values = _body_values(m, body, require_all=False)
        values.pop(m["pk"], None)
        byname = {c["name"]: c for c in m["columns"]}
        sets, params = [], []
        for k, v in values.items():
            e, p = _value(byname[k], v)
            sets.append(sql.SQL("{} = {}").format(sql.Identifier(k), e))
            if p is not None:
                params.append(p)
        if not sets:
            raise RestError("هیچ ستونی برای ویرایش فرستاده نشده است.")
        params.append(pk_value)
        q = sql.SQL("UPDATE {} SET {} WHERE {} = CAST(%s AS {}) RETURNING {}").format(
            sql.Identifier(schema, table), sql.SQL(", ").join(sets), sql.Identifier(m["pk"]),
            sql.SQL(byname[m["pk"]]["type"]), _select(m))
        cur = _exec_write(conn, q, params)
        row = cur.fetchone()
        if row is None:
            raise RestError("سطر پیدا نشد.", 404)
        out = _row_out(m, [d.name for d in cur.description], row)
        conn.commit()
        return out


def delete(db, schema, table, pk_value) -> None:
    with _conn(db, True) as conn:
        m = meta(conn, schema, table)
        _need_pk(m)
        pkc = next(c for c in m["columns"] if c["name"] == m["pk"])
        cur = _exec_write(conn, sql.SQL("DELETE FROM {} WHERE {} = CAST(%s AS {})").format(
            sql.Identifier(schema, table), sql.Identifier(m["pk"]), sql.SQL(pkc["type"])), [pk_value])
        if cur.rowcount == 0:
            raise RestError("سطر پیدا نشد.", 404)
        conn.commit()
