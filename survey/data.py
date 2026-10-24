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
