from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Isochrone(ToolPlugin):
    key, order, category, icon = "isochrone", 10, "network", "t-isochrone"
    level = "mid"
    popular = True
    title = "حوزه دسترسی"
    description = "محدوده‌ای که از یک نقطه با پیمودن فاصله مشخص روی شبکه معابر می‌رسید."
    inputs, output = ("نقطهٔ شروع",), "محدودهٔ دسترسی"
    example = "تا کجا می‌شود از یک نقطه با ۱۰۰۰ متر پیاده‌روی روی خیابان‌ها رسید."
    columns = ("distance_m", "edges", "geom")
    needs_routing = True
    params = (
        Param("lon", "text", "طول جغرافیایی", "نقطهٔ شروع", placeholder="51.389"),
        Param("lat", "text", "عرض جغرافیایی", placeholder="35.700"),
        Param("distance", "number", "فاصله روی شبکه معابر", default="1000", unit="متر"),
    )

    def build(self, ctx):
        ctx.need_routing()
        lon, lat = ctx.number("lon", -180, 180), ctx.number("lat", -90, 90)
        dist = ctx.number("distance", 50, 50_000)
        return sql.SQL(
            "WITH s AS (SELECT id FROM routing.ways_vertices_pgr "
            "ORDER BY the_geom <-> ST_SetSRID(ST_MakePoint({lon}, {lat}), 4326) LIMIT 1), "
            "d AS (SELECT * FROM pgr_drivingDistance('SELECT gid AS id, source, target, length_m AS cost, "
            "CASE WHEN reverse_cost < 0 THEN -1 ELSE length_m END AS reverse_cost FROM routing.ways', "
            "(SELECT id FROM s), {dist})), "
            "e AS (SELECT w.the_geom FROM routing.ways w JOIN d ON d.edge = w.gid) "
            "SELECT {dist}::int AS distance_m, count(*) AS edges, "
            "ST_Multi(ST_ConcaveHull(ST_Collect(e.the_geom), 0.3))::geometry(MultiPolygon, 4326) AS geom FROM e").format(
            lon=sql.Literal(lon), lat=sql.Literal(lat), dist=sql.Literal(dist))

    def summary_extra(self, params):
        return [f"از {params.get('lon')}, {params.get('lat')}"] if params.get("lon") else []
