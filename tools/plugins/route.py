from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class Route(ToolPlugin):
    key, order, category, icon = "route", 20, "network", "t-route"
    popular = True
    title = "کوتاه‌ترین مسیر"
    description = "کوتاه‌ترین مسیر روی شبکه معابر بین دو نقطه، با طول آن به متر."
    inputs, output = ("دو نقطه",), "خط مسیر + طول"
    example = "کوتاه‌ترین مسیر خودرو از یک نقطه تا نقطه‌ی دیگر روی خیابان‌ها."
    columns = ("distance_m", "edges", "geom")
    needs_routing = True
    params = (
        Param("lon", "text", "طول جغرافیایی مبدأ", placeholder="51.389"),
        Param("lat", "text", "عرض جغرافیایی مبدأ", placeholder="35.700"),
        Param("lon2", "text", "طول جغرافیایی مقصد", placeholder="51.420"),
        Param("lat2", "text", "عرض جغرافیایی مقصد", placeholder="35.720"),
    )

    def build(self, ctx):
        ctx.need_routing()
        lon, lat = ctx.number("lon", -180, 180), ctx.number("lat", -90, 90)
        lon2, lat2 = ctx.number("lon2", -180, 180), ctx.number("lat2", -90, 90)
        return sql.SQL(
            "WITH s AS (SELECT id FROM routing.ways_vertices_pgr {s}), t AS (SELECT id FROM routing.ways_vertices_pgr {t}), "
            "r AS (SELECT * FROM pgr_dijkstra({edges}, (SELECT id FROM s), (SELECT id FROM t), true) WHERE edge > 0) "
            "SELECT round(sum(r.cost)::numeric, 1) AS distance_m, count(*) AS edges, "
            "ST_Multi(ST_LineMerge(ST_Collect(w.the_geom ORDER BY r.seq)))::geometry(MultiLineString, 4326) AS geom "
            "FROM r JOIN routing.ways w ON w.gid = r.edge HAVING count(*) > 0").format(
            s=sdk.nearest_vertex(lon, lat), t=sdk.nearest_vertex(lon2, lat2), edges=sql.SQL(sdk.EDGES))

    def after_create(self, conn, target):
        if conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0] == 0:
            raise ToolError("مسیری بین این دو نقطه روی شبکه معابر پیدا نشد (شاید در دو بخش جدا از هم هستند).")

    def summary_extra(self, params):
        out = [f"از {params.get('lon')}, {params.get('lat')}"] if params.get("lon") else []
        if params.get("lon2"):
            out.append(f"تا {params.get('lon2')}, {params.get('lat2')}")
        return out
