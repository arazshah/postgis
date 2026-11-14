from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class RingBuffer(ToolPlugin):
    key, order, category, icon = "ringbuf", 20, "proximity", "t-ringbuf"
    level = "mid"
    title = "حریم چندحلقه‌ای"
    description = "دور هر عارضه چند حلقه‌ی هم‌فاصله می‌سازد (مثلاً ۵۰۰، ۱۰۰۰ و ۱۵۰۰ متر) بدون همپوشانی حلقه‌ها."
    inputs, output = ("هر لایه",), "حلقه‌های حریم + شماره حلقه"
    example = "سه حلقه‌ی ۴۰۰ متری دور ایستگاه‌های مترو برای بررسی کاهش دسترسی با فاصله."
    columns = ("ستون‌های لایه ورودی", "ring", "from_m", "to_m", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("distance", "number", "پهنای هر حلقه", "فاصله‌ی هر حلقه با حلقه‌ی قبلی", "500", unit="متر"),
        Param("rings", "number", "تعداد حلقه‌ها", "بین ۲ تا ۱۰", "3", unit="حلقه"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        d, n = ctx.number("distance", 1, 50_000), int(ctx.number("rings", 2, 10))
        ctx.guard(t, col, 20_000, "حریم چندحلقه‌ای تا ۲۰٬۰۰۰ عارضه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}r.i AS ring, ((r.i - 1) * {d})::float8 AS from_m, (r.i * {d})::float8 AS to_m, "
            "CASE WHEN r.i = 1 THEN ST_Buffer({g}::geography, {d})::geometry "
            "ELSE ST_Difference(ST_Buffer({g}::geography, r.i * {d})::geometry, ST_Buffer({g}::geography, (r.i - 1) * {d})::geometry) "
            "END AS geom FROM {src} s CROSS JOIN generate_series(1, {n}) AS r(i) WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, d=sql.Literal(d), n=sql.Literal(n), src=sdk.ident(t), c=sql.Identifier(col))

    def summary_extra(self, params):
        return [f"{params['rings']} حلقه"] if params.get("rings") else []
