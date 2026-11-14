from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Compact(ToolPlugin):
    key, order, category, icon = "compact", 40, "measure", "t-compact"
    level = "mid"
    title = "شاخص شکل (فشردگی)"
    description = "فشردگی هر چندضلعی را با شاخص پولسبی–پوپر (۱ = دایره‌ی کامل) می‌سنجد و شکل‌های کشیده یا پیچیده را نشان می‌دهد."
    inputs, output = ("لایه چندضلعی",), "چندضلعی‌ها + شاخص و رده‌ی شکل"
    example = "شناسایی حوزه‌های انتخاباتی با شکل غیرعادی، یا قطعه‌های باریک و کشیده."
    columns = ("ستون‌های لایه ورودی", "area_m2", "perimeter_m", "compactness", "shape_class", "geom")
    chart_hint = {"kind": "hist", "field": "compactness"}
    params = (Param("layer", "layer", "لایه چندضلعی", geom="polygon"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POLYGON",), ctx.ex)
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}round(m.a::numeric, 1) AS area_m2, round(m.p::numeric, 1) AS perimeter_m, "
            "round((4 * pi() * m.a / NULLIF(m.p * m.p, 0))::numeric, 3) AS compactness, "
            "CASE WHEN 4 * pi() * m.a / NULLIF(m.p * m.p, 0) >= 0.7 THEN 'compact' "
            "WHEN 4 * pi() * m.a / NULLIF(m.p * m.p, 0) >= 0.4 THEN 'moderate' ELSE 'irregular' END AS shape_class, "
            "{g}::geometry AS geom FROM {src} s CROSS JOIN LATERAL (SELECT ST_Area({g}::geography) AS a, "
            "ST_Perimeter({g}::geography) AS p) m WHERE s.{c} IS NOT NULL AND m.p > 0").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, src=sdk.ident(t), c=sql.Identifier(col))
