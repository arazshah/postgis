from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Bearing(ToolPlugin):
    key, order, category, icon = "bearing", 50, "measure", "t-bearing"
    level = "mid"
    title = "جهت و پیچ‌وخم خط"
    description = "آزیموت (جهت از شمال)، جهت اصلی، طول، فاصله‌ی مستقیم و ضریب پیچ‌وخم هر خط را حساب می‌کند."
    inputs, output = ("لایه خطی",), "خط‌ها + ستون‌های جهت و پیچ‌وخم"
    example = "جهت غالب خیابان‌های هر محله، یا میزان پیچ‌وخم رودخانه‌ها."
    columns = ("ستون‌های لایه ورودی", "azimuth_deg", "direction", "length_m", "straight_m", "sinuosity", "geom")
    params = (Param("layer", "layer", "لایه خطی", geom="line"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE",), ctx.ex)
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}round(m.az::numeric, 1) AS azimuth_deg, "
            "(ARRAY['N','NE','E','SE','S','SW','W','NW'])[1 + (round(m.az / 45.0)::int % 8)] AS direction, "
            "round(m.len::numeric, 1) AS length_m, round(m.st::numeric, 1) AS straight_m, "
            "round((m.len / NULLIF(m.st, 0))::numeric, 3) AS sinuosity, {g}::geometry AS geom FROM {src} s "
            "CROSS JOIN LATERAL (SELECT ST_GeometryN(ST_LineMerge(ST_Multi({g})), 1) AS l) x "
            "CROSS JOIN LATERAL (SELECT degrees(ST_Azimuth(ST_StartPoint(x.l)::geography, ST_EndPoint(x.l)::geography)) AS az, "
            "ST_Length({g}::geography) AS len, ST_Distance(ST_StartPoint(x.l)::geography, ST_EndPoint(x.l)::geography) AS st) m "
            "WHERE s.{c} IS NOT NULL AND m.az IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, src=sdk.ident(t), c=sql.Identifier(col))
