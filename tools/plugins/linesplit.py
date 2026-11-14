from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

CAP = 500_000


@sdk.register
class LineSplit(ToolPlugin):
    key, order, category, icon = "linesplit", 20, "linear", "t-linesplit"
    level = "mid"
    title = "تقسیم خط به قطعه‌های هم‌طول"
    description = "هر خط را به قطعه‌هایی با طول مشخص می‌شکند؛ آخرین قطعه ممکن است کوتاه‌تر باشد."
    inputs, output = ("لایه خطی",), "قطعه‌های خط + طول هر قطعه"
    example = "تقسیم محور جاده به قطعه‌های ۵۰۰ متری برای ثبت وضعیت روسازی."
    columns = ("ستون‌های لایه ورودی", "seg_no", "length_m", "geom")
    params = (
        Param("layer", "layer", "لایه خطی", geom="line"),
        Param("distance", "number", "طول هر قطعه", "", "500", unit="متر"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE",), ctx.ex)
        d = ctx.number("distance", 1, 100_000)
        g = sdk.geom4326("s", col, srid)
        ctx.guards.append((sql.SQL("SELECT coalesce(ceil(sum(ST_Length({g}::geography)) / {d}), 0)::bigint FROM {src} s WHERE s.{c} IS NOT NULL").format(
            g=g, d=sql.Literal(d), src=sdk.ident(t), c=sql.Identifier(col)), CAP,
            "تعداد قطعه‌ها از ۵۰۰٬۰۰۰ بیشتر می‌شود؛ طول قطعه را بیشتر کنید."))
        return sql.SQL(
            "SELECT {attrs}i.n + 1 AS seg_no, round(least({d}, l.len - i.n * {d})::numeric, 1) AS length_m, "
            "ST_LineSubstring(ln.geom, least(i.n * {d} / l.len, 1), least((i.n + 1) * {d} / l.len, 1)) AS geom FROM {src} s "
            "CROSS JOIN LATERAL ST_Dump({g}) ln CROSS JOIN LATERAL (SELECT ST_Length(ln.geom::geography) AS len) l "
            "CROSS JOIN LATERAL generate_series(0, greatest(ceil(l.len / {d})::int - 1, 0)) AS i(n) "
            "WHERE s.{c} IS NOT NULL AND l.len > 0 AND GeometryType(ln.geom) = 'LINESTRING'").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), d=sql.Literal(d), g=g, src=sdk.ident(t), c=sql.Identifier(col))
