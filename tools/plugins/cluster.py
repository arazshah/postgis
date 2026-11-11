from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Cluster(ToolPlugin):
    key, order, category, icon = "cluster", 100, "aggregate", "t-cluster"
    title = "خوشه‌بندی نقطه‌ها"
    description = "نقطه‌های نزدیک به هم را خوشه می‌کند و دور هر خوشه چندضلعی و تعدادش را می‌دهد؛ برای یافتن کانون‌ها."
    inputs, output = ("لایه نقطه‌ای",), "چندضلعی هر خوشه + تعداد"
    example = "کانون‌های تصادف: جاهایی که دست‌کم ۵ تصادف در شعاع ۲۰۰ متر دارند."
    columns = ("cluster_id", "point_count", "geom")
    chart_hint = {"kind": "hist", "field": "point_count"}
    params = (
        Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
        Param("distance", "number", "شعاع همسایگی (متر)", "نقطه‌های نزدیک‌تر از این فاصله به هم می‌پیوندند", "200"),
        Param("minpoints", "number", "حداقل نقطه در هر خوشه", "گروه‌های کوچک‌تر نقطهٔ پراکنده حساب می‌شوند", "5"),
    )

    def build(self, ctx):
        p = ctx.table("layer")
        cp, sp, _ = sdk.geom_of(p, ("POINT",), ctx.ex)
        eps, n = ctx.number("distance", 1, 100_000), int(ctx.number("minpoints", 2, 1000))
        return sql.SQL(
            "WITH pts AS (SELECT {g}::geometry AS g FROM {P} p WHERE p.{cp} IS NOT NULL), "
            "k AS (SELECT greatest(cos(radians(least(abs(avg(ST_Y(g))), 85))), 0.05) AS c FROM pts), "
            "cl AS (SELECT g, ST_ClusterDBSCAN(ST_Transform(g, 3857), eps := {eps} / (SELECT c FROM k), minpoints := {n}) OVER () AS cid "
            "FROM pts) "
            "SELECT (cid + 1)::int AS cluster_id, count(*) AS point_count, "
            "ST_Buffer(ST_ConvexHull(ST_Collect(g))::geography, least({eps} * 0.1, 50))::geometry(Polygon, 4326) AS geom "
            "FROM cl WHERE cid IS NOT NULL GROUP BY cid").format(
            g=sdk.geom4326("p", cp, sp), P=sdk.ident(p), cp=sql.Identifier(cp), eps=sql.Literal(eps), n=sql.Literal(n))

    def summary_extra(self, params):
        return [f"حداقل {params['minpoints']} نقطه"] if params.get("minpoints") else []
