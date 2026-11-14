from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class GeomStats(ToolPlugin):
    key, order, category, icon = "geomstats", 10, "measure", "t-geomstats"
    popular = True
    title = "مساحت، محیط و طول"
    description = "مساحت (متر مربع و هکتار)، محیط یا طول و تعداد رأس هر عارضه را به‌صورت ستون به لایه اضافه می‌کند."
    inputs, output = ("هر لایه",), "همان عارضه‌ها + ستون‌های اندازه"
    example = "مساحت هر قطعه زمین به هکتار، یا طول هر خیابان به متر."
    columns = ("ستون‌های لایه ورودی", "area_m2", "area_ha", "length_m", "vertices", "geom")
    params = (Param("layer", "layer", "لایه ورودی"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}round(ST_Area({g}::geography)::numeric, 1) AS area_m2, "
            "round((ST_Area({g}::geography) / 10000.0)::numeric, 3) AS area_ha, "
            "round((CASE WHEN ST_Dimension({g}) = 2 THEN ST_Perimeter({g}::geography) WHEN ST_Dimension({g}) = 1 "
            "THEN ST_Length({g}::geography) ELSE 0 END)::numeric, 1) AS length_m, ST_NPoints({g}) AS vertices, "
            "{g}::geometry AS geom FROM {src} s WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, src=sdk.ident(t), c=sql.Identifier(col))
