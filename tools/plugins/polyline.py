from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class PolyToLine(ToolPlugin):
    key, order, category, icon = "polyline", 80, "geometry", "t-polyline"
    title = "مرز چندضلعی به خط"
    description = "مرز بیرونی (و حفره‌های) چندضلعی‌ها را به عارضه‌ی خطی تبدیل می‌کند و طول مرز را می‌دهد."
    inputs, output = ("لایه چندضلعی",), "خط مرز + طول"
    example = "استخراج مرز محله‌ها برای رسم خط ضخیم یا شمردن طول مرز مشترک."
    columns = ("ستون‌های لایه ورودی", "perimeter_m", "geom")
    params = (Param("layer", "layer", "لایه چندضلعی", geom="polygon"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POLYGON",), ctx.ex)
        return sql.SQL("SELECT {attrs}round(ST_Length(b.g::geography)::numeric, 1) AS perimeter_m, b.g AS geom FROM {src} s "
                       "CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_Boundary(ST_MakeValid({g})), 2) AS g) b "
                       "WHERE s.{c} IS NOT NULL AND NOT ST_IsEmpty(b.g)").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col))
