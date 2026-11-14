from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Coords(ToolPlugin):
    key, order, category, icon = "coords", 30, "measure", "t-coords"
    title = "مختصات و منطقه‌ی UTM"
    description = "طول و عرض جغرافیایی، منطقه‌ی UTM و مختصات متری (X, Y) نقطه‌ی نماینده‌ی هر عارضه را به جدول می‌افزاید."
    inputs, output = ("هر لایه",), "همان عارضه‌ها + مختصات"
    example = "دریافت مختصات UTM تمام چاه‌ها برای گزارش به سازمان دیگر."
    columns = ("ستون‌های لایه ورودی", "lon", "lat", "utm_zone", "utm_epsg", "utm_x", "utm_y", "geom")
    params = (Param("layer", "layer", "لایه ورودی"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        ctx.guard(t, col, 200_000, "این ابزار تا ۲۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}round(ST_X(c.p)::numeric, 6) AS lon, round(ST_Y(c.p)::numeric, 6) AS lat, c.zone AS utm_zone, c.epsg AS utm_epsg, "
            "round(ST_X(u.p)::numeric, 1) AS utm_x, round(ST_Y(u.p)::numeric, 1) AS utm_y, {g}::geometry AS geom FROM {src} s "
            "CROSS JOIN LATERAL (SELECT ST_PointOnSurface({g}) AS p) c0 "
            "CROSS JOIN LATERAL (SELECT c0.p AS p, floor((ST_X(c0.p) + 180) / 6)::int + 1 AS zone, "
            "(CASE WHEN ST_Y(c0.p) >= 0 THEN 32600 ELSE 32700 END) + floor((ST_X(c0.p) + 180) / 6)::int + 1 AS epsg) c "
            "CROSS JOIN LATERAL (SELECT ST_Transform(c.p, c.epsg) AS p) u WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, src=sdk.ident(t), c=sql.Identifier(col))
