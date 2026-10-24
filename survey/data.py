"""خواندن داده پروژه برداشت برای نقشه، جدول و خروجی‌ها."""
import json

from psycopg import sql

from databases.explorer import Explorer

from . import ddl

POINT_COLS = ("id", "client_uuid", "pt_no", "code", "descr", "fix_quality", "sats", "hdop", "pdop", "acc_h",
              "std_e", "std_n", "std_h", "h_ellip", "h_ortho", "antenna_h", "corr_age", "captured_at", "captured_by",
              "device", "driver_id", "session_id")
LINE_COLS = ("id", "client_uuid", "code", "descr", "captured_at", "captured_by", "session_id")
LIMIT = 20000


def _rows(conn, project, table, cols, limit):
    ddl.check_slug(project.slug)
    xy = table == "points"
    q = sql.SQL("SELECT {cols}, ST_AsGeoJSON(ST_Transform(geom, 4326))::text{xy} "
                "FROM {t} WHERE deleted_at IS NULL ORDER BY id LIMIT %s").format(
        cols=sql.SQL(", ").join(map(sql.Identifier, cols)), t=sql.Identifier(project.slug, table),
        xy=sql.SQL(", ST_X(geom), ST_Y(geom)" if xy else ""))
    out = []
    for row in conn.execute(q, (limit,)).fetchall():
        props = {c: (v.isoformat() if hasattr(v, "isoformat") else (str(v) if c in ("client_uuid", "session_id") and v else v))
                 for c, v in zip(cols, row[:len(cols)], strict=True)}
        if xy:
            props["x"], props["y"] = row[-2], row[-1]
        out.append({"type": "Feature", "id": props["id"], "geometry": json.loads(row[len(cols)]), "properties": props})
    return out


def collections(db, project, limit: int = LIMIT) -> dict:
    """سه مجموعه GeoJSON (۴۳۲۶) و مختصات پروژه (x و y) در properties نقاط."""
    with Explorer(db).connect() as conn:
        return {
            "points": {"type": "FeatureCollection", "features": _rows(conn, project, "points", POINT_COLS, limit)},
            "lines": {"type": "FeatureCollection", "features": _rows(conn, project, "lines", LINE_COLS, limit)},
            "polygons": {"type": "FeatureCollection", "features": _rows(conn, project, "polygons", LINE_COLS, limit)},
        }


def counts(db, project) -> dict:
    ddl.check_slug(project.slug)
    with Explorer(db).connect() as conn:
        return {t: conn.execute(sql.SQL("SELECT count(*) FROM {} WHERE deleted_at IS NULL").format(
            sql.Identifier(project.slug, t))).fetchone()[0] for t in ("points", "lines", "polygons")}


def codes(db, project) -> list[dict]:
    ddl.check_slug(project.slug)
    with Explorer(db).connect() as conn:
        rows = conn.execute(sql.SQL("SELECT code, name, geom_type, layer FROM {} ORDER BY sort, code").format(
            sql.Identifier(project.slug, "codes"))).fetchall()
    return [{"code": r[0], "name": r[1], "geom_type": r[2], "layer": r[3]} for r in rows]


def projected_lines(db, project) -> dict:
    """مختصات خط و چندضلعی در سیستم مختصات پروژه (برای DXF)؛ ترتیب همان collections است."""
    out = {}
    with Explorer(db).connect() as conn:
        for key, table in (("lines", "lines"), ("polygons", "polygons")):
            rows = conn.execute(sql.SQL("SELECT ST_AsGeoJSON(geom)::text FROM {} WHERE deleted_at IS NULL "
                                        "ORDER BY id LIMIT %s").format(sql.Identifier(project.slug, table)),
                                (LIMIT,)).fetchall()
            coords = []
            for (g,) in rows:
                c = json.loads(g)["coordinates"]
                coords.append([(x, y) for x, y, *_ in (c[0] if key == "polygons" else c)])
            out[key] = coords
    return out


# ----------------------------------------------------------------------------- سطح (TIN) و منحنی میزان
HEIGHT_FIELDS = ("h_ortho", "h_ellip")
MAX_TIN_POINTS = 50000


def tin(db, project, field: str):
    """مثلث‌های Delaunay نقاط دارای ارتفاع (مختصات پروژه). نقاط هم‌مکان (به دقت میلی‌متر) میانگین‌گیری می‌شوند."""
    from .surface import SurfaceError
    if field not in HEIGHT_FIELDS:
        raise SurfaceError("ستون ارتفاع نامعتبر است.")
    ddl.check_slug(project.slug)
    t, f = sql.Identifier(project.slug, "points"), sql.Identifier(field)
    with Explorer(db).connect() as conn:
        n = conn.execute(sql.SQL("SELECT count(*) FROM {t} WHERE deleted_at IS NULL AND {f} IS NOT NULL").format(t=t, f=f)).fetchone()[0]
        if n < 3:
            raise SurfaceError("برای ساخت سطح دست‌کم ۳ نقطه با ارتفاع لازم است.")
        if n > MAX_TIN_POINTS:
            raise SurfaceError(f"حداکثر {MAX_TIN_POINTS} نقطه برای ساخت سطح پشتیبانی می‌شود.")
        rows = conn.execute(sql.SQL("""
            WITH p AS (SELECT round(ST_X(geom)::numeric, 3) AS x, round(ST_Y(geom)::numeric, 3) AS y, avg({f}) AS z
                       FROM {t} WHERE deleted_at IS NULL AND {f} IS NOT NULL GROUP BY 1, 2)
            SELECT ST_AsGeoJSON(d.geom, 6)::text
            FROM (SELECT ST_Collect(ST_MakePoint(x::float8, y::float8, z::float8)) AS g FROM p) c,
                 LATERAL ST_Dump(ST_DelaunayTriangles(c.g)) d""").format(t=t, f=f)).fetchall()
    tris = []
    for (g,) in rows:
        ring = json.loads(g)["coordinates"][0][:3]
        if len(ring) == 3 and all(len(c) == 3 for c in ring):
            tris.append(tuple(tuple(c) for c in ring))
    if not tris:
        raise SurfaceError("نقاط روی یک خط‌اند و سطحی نمی‌سازند.")
    return tris, n


def _wkt(coords) -> str:
    return "LINESTRING(" + ",".join(f"{x:.4f} {y:.4f}" for x, y in coords) + ")"


def contours_wgs84(db, project, lines: list[dict]) -> dict:
    """منحنی‌ها (مختصات پروژه) ← GeoJSON با طول و عرض جغرافیایی برای نقشه."""
    if not lines:
        return {"type": "FeatureCollection", "features": []}
    ddl.check_slug(project.slug)
    with Explorer(db).connect() as conn:
        rows = conn.execute("SELECT ST_AsGeoJSON(ST_Transform(ST_SetSRID(ST_GeomFromText(w), %s), 4326), 7)::text "
                            "FROM unnest(%s::text[]) WITH ORDINALITY AS u(w, i) ORDER BY i",
                            (project.srid, [_wkt(c["coords"]) for c in lines])).fetchall()
    feats = [{"type": "Feature", "geometry": json.loads(g),
              "properties": {"level": c["level"], "index": 1 if c["index"] else 0}} for (g,), c in zip(rows, lines, strict=True)]
    return {"type": "FeatureCollection", "features": feats}


def save_contours(db, project, lines: list[dict]) -> int:
    """جدول معمولی <schema>.contours (برای نقشه‌های چندلایه، REST و QGIS)؛ هر بار جایگزین می‌شود."""
    ddl.check_slug(project.slug)
    t = sql.Identifier(project.slug, "contours")
    with Explorer(db).connect(read_only=False) as conn:
        conn.execute(sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(db.role_name)))
        conn.execute(sql.SQL("""CREATE TABLE IF NOT EXISTS {t} (id serial PRIMARY KEY, level double precision NOT NULL,
            is_index boolean NOT NULL DEFAULT false, created_at timestamptz NOT NULL DEFAULT now(),
            geom geometry(LineString, {srid}) NOT NULL)""").format(t=t, srid=sql.Literal(int(project.srid))))
        conn.execute(sql.SQL("CREATE INDEX IF NOT EXISTS {i} ON {t} USING gist (geom)").format(
            i=sql.Identifier("contours_geom_gix"), t=t))
        conn.execute(sql.SQL("DELETE FROM {t}").format(t=t))
        with conn.cursor() as cur:
            cur.executemany(sql.SQL("INSERT INTO {t} (level, is_index, geom) VALUES (%s, %s, ST_SetSRID(ST_GeomFromText(%s), %s))")
                            .format(t=t), [(c["level"], c["index"], _wkt(c["coords"]), project.srid) for c in lines])
        conn.commit()
    return len(lines)
