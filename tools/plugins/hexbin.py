from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Hexbin(ToolPlugin):
    key, order, category, icon = "hexbin", 20, "aggregate", "t-hexbin"
    popular = True
    title = "نقشه تراکم شش‌ضلعی"
    description = "شبکه شش‌ضلعی روی نقطه‌ها و تعداد هر خانه؛ برای نقشه حرارتی."
    inputs, output = ("لایه نقطه‌ای",), "شبکه شش‌ضلعی + تعداد"
    example = "نقشهٔ حرارتی تصادفات یا مدرسه‌ها با خانه‌های ۵۰۰ متری."
    columns = ("count", "geom")
    chart_hint = {"kind": "hist", "field": "count"}
    params = (
        Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
        Param("size", "number", "اندازه‌ی هر خانه", "ضلع تقریبی هر شش‌ضلعی", "500", unit="متر"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        size = ctx.number("size", 20, 50_000)
        g3857 = sql.SQL("ST_Transform({}, 3857)").format(sdk.geom4326("s", col, srid))
        return sql.SQL(
            "WITH pts AS (SELECT {g} AS g FROM {src} s WHERE s.{c} IS NOT NULL), "
            "grid AS (SELECT h.geom FROM ST_HexagonGrid({size}, (SELECT ST_SetSRID(ST_Extent(g)::geometry, 3857) FROM pts)) h) "
            "SELECT count(*) AS count, ST_Transform(grid.geom, 4326)::geometry(Polygon, 4326) AS geom "
            "FROM grid JOIN pts ON ST_Intersects(grid.geom, pts.g) GROUP BY grid.geom").format(
            g=g3857, src=sdk.ident(t), c=sql.Identifier(col), size=sql.Literal(size))
