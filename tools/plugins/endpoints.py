from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class EndPoints(ToolPlugin):
    key, order, category, icon = "endpoints", 40, "linear", "t-endpoints"
    title = "نقاط ابتدا و انتهای خط"
    description = "نقطه‌ی شروع، پایان یا هر دو سر هر خط را به‌صورت نقطه می‌سازد."
    inputs, output = ("لایه خطی",), "نقطه‌های سر خط"
    example = "ورودی و خروجی هر خط لوله، یا سرانجام‌های بن‌بست‌ها در شبکه‌ی راه."
    columns = ("ستون‌های لایه ورودی", "end_type", "geom")
    params = (
        Param("layer", "layer", "لایه خطی", geom="line"),
        Param("which", "choice", "کدام سر", default="both", required=False,
              choices=(("both", "هر دو سر"), ("start", "فقط ابتدا"), ("end", "فقط انتها"))),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE",), ctx.ex)
        which = ctx.choice("which", ("both", "start", "end"), "both")
        flt = sql.SQL("") if which == "both" else sql.SQL(" AND e.kind = {}").format(sql.Literal(which))
        return sql.SQL(
            "SELECT {attrs}e.kind AS end_type, e.geom AS geom FROM {src} s CROSS JOIN LATERAL ST_Dump({g}) ln "
            "CROSS JOIN LATERAL (VALUES ('start', ST_StartPoint(ln.geom)), ('end', ST_EndPoint(ln.geom))) AS e(kind, geom) "
            "WHERE s.{c} IS NOT NULL AND GeometryType(ln.geom) = 'LINESTRING'{flt}").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col), flt=flt)
