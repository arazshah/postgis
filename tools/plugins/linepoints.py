from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

CAP = 1_000_000


@sdk.register
class LinePoints(ToolPlugin):
    key, order, category, icon = "linepoints", 10, "linear", "t-linepoints"
    level = "mid"
    title = "نقطه‌گذاری روی خط"
    description = "روی هر خط، هر چند متر یک نقطه می‌گذارد و فاصله‌ی هر نقطه از ابتدای خط را می‌دهد (کیلومتراژ)."
    inputs, output = ("لایه خطی",), "نقطه‌های هم‌فاصله + فاصله از ابتدا"
    example = "نقطه‌گذاری هر ۱۰۰ متر روی محور جاده برای بازرسی یا نمونه‌برداری."
    columns = ("ستون‌های لایه ورودی", "seq", "at_m", "geom")
    params = (
        Param("layer", "layer", "لایه خطی", geom="line"),
        Param("distance", "number", "فاصله‌ی نقطه‌ها", "هر چند متر یک نقطه", "100", unit="متر"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE",), ctx.ex)
        d = ctx.number("distance", 1, 100_000)
        g = sdk.geom4326("s", col, srid)
        ctx.guards.append((sql.SQL("SELECT coalesce(ceil(sum(ST_Length({g}::geography)) / {d}), 0)::bigint FROM {src} s WHERE s.{c} IS NOT NULL").format(
            g=g, d=sql.Literal(d), src=sdk.ident(t), c=sql.Identifier(col)), CAP,
            "تعداد نقطه‌ها از یک میلیون بیشتر می‌شود؛ فاصله را بیشتر کنید."))
        return sql.SQL(
            "SELECT {attrs}p.path[1] AS seq, round((p.path[1] * {d})::numeric, 1) AS at_m, p.geom AS geom FROM {src} s "
            "CROSS JOIN LATERAL ST_Dump({g}) ln CROSS JOIN LATERAL (SELECT ST_Length(ln.geom::geography) AS len) l "
            "CROSS JOIN LATERAL ST_Dump(ST_LineInterpolatePoints(ln.geom, least({d} / l.len, 1), true)) p "
            "WHERE s.{c} IS NOT NULL AND l.len > 0 AND GeometryType(ln.geom) = 'LINESTRING'").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), d=sql.Literal(d), g=g, src=sdk.ident(t), c=sql.Identifier(col))
