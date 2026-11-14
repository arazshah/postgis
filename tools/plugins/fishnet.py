from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

MAX_CELLS = 400_000


@sdk.register
class Fishnet(ToolPlugin):
    key, order, category, icon = "fishnet", 30, "aggregate", "t-fishnet"
    popular = True
    title = "شبکه‌ی مربعی و شمارش"
    description = "روی منطقه شبکه‌ی مربعی منظم می‌سازد و تعداد عارضه‌های هر خانه و چگالی آن را می‌دهد."
    inputs, output = ("هر لایه",), "خانه‌های مربعی + تعداد و چگالی"
    example = "نقشه‌ی تراکم جرایم با خانه‌های ۲۵۰ متری، قابل مقایسه با سال‌های دیگر."
    columns = ("count", "density_km2", "geom")
    chart_hint = {"kind": "hist", "field": "count"}
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("size", "number", "ضلع هر خانه", "اندازه‌ی ضلع مربع‌ها", "500", unit="متر"),
        Param("empty", "bool", "خانه‌های خالی هم بیایند", "برای شبکه‌ی کامل منطقه", required=False, group="advanced"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        size = ctx.number("size", 10, 100_000)
        ctx.guard(t, col, 500_000, "این ابزار تا ۵۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        # سقف تعداد خانه‌ها: مساحت جعبه‌ی لایه / مساحت خانه (در سیستم مختصات وب‌مرکاتور، تقریبی)
        ext = sql.SQL("SELECT ST_SetSRID(ST_Extent(ST_Transform({g}, 3857))::geometry, 3857) FROM {src} s WHERE s.{c} IS NOT NULL").format(
            g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col))
        ctx.guards.append((sql.SQL("SELECT coalesce(ceil((ST_XMax(e.b) - ST_XMin(e.b)) / {s}) * ceil((ST_YMax(e.b) - ST_YMin(e.b)) / {s}), 0)::bigint "
                                   "FROM (SELECT ({ext}) AS b) e").format(s=sql.Literal(size), ext=ext), MAX_CELLS,
                           "تعداد خانه‌های شبکه از ۴۰۰٬۰۰۰ بیشتر می‌شود؛ اندازه‌ی خانه را بزرگ‌تر کنید."))
        keep = ctx.params.get("empty") == "on"
        return sql.SQL(
            "WITH pts AS (SELECT ST_Transform({g}, 3857) AS g FROM {src} s WHERE s.{c} IS NOT NULL), "
            "grid AS (SELECT q.geom FROM ST_SquareGrid({size}, (SELECT ST_SetSRID(ST_Extent(g)::geometry, 3857) FROM pts)) q) "
            "SELECT count(pts.g) AS count, round((count(pts.g) / (ST_Area(grid.geom) / 1e6))::numeric, 2) AS density_km2, "
            "ST_Transform(grid.geom, 4326)::geometry(Polygon, 4326) AS geom FROM grid {join} pts ON ST_Intersects(grid.geom, pts.g) "
            "GROUP BY grid.geom").format(
            g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col), size=sql.Literal(size),
            join=sql.SQL("LEFT JOIN" if keep else "JOIN"))

    def summary_extra(self, params):
        return [f"خانه {params['size']} متر"] if params.get("size") else []
