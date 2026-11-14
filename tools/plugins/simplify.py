from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Simplify(ToolPlugin):
    key, order, category, icon = "simplify", 60, "geometry", "t-simplify"
    level = "mid"
    title = "ساده‌سازی خط و چندضلعی"
    description = "تعداد رأس‌ها را کم می‌کند تا فایل سبک‌تر و نقشه سریع‌تر شود؛ شکل کلی و توپولوژی حفظ می‌شود."
    inputs, output = ("خط یا چندضلعی",), "هندسه‌ی ساده‌شده + شمار رأس قبل و بعد"
    example = "مرز شهرستان‌ها را برای نقشه‌ی وب با تلرانس ۵۰ متر سبک کن."
    columns = ("ستون‌های لایه ورودی", "vertices_before", "vertices_after", "geom")
    params = (
        Param("layer", "layer", "لایه خطی یا چندضلعی"),
        Param("tolerance", "number", "تلرانس ساده‌سازی", "بیشترین جابه‌جایی مجاز هر رأس", "20", unit="متر"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("LINE", "POLYGON"), ctx.ex)
        tol = ctx.number("tolerance", 0.1, 10_000)
        ctx.guard(t, col, 100_000, "این ابزار تا ۱۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        g = sdk.geom4326("s", col, srid)
        adj = sql.SQL("({tol} / greatest(cos(radians(ST_Y(ST_PointOnSurface({g})))), 0.05))").format(tol=sql.Literal(tol), g=g)
        s_ = sql.SQL("ST_Transform(ST_SimplifyPreserveTopology(ST_Transform({g}, 3857), {adj}), 4326)").format(g=g, adj=adj)
        return sql.SQL("SELECT {attrs}ST_NPoints({g}) AS vertices_before, ST_NPoints(r.g) AS vertices_after, r.g AS geom FROM {src} s "
                       "CROSS JOIN LATERAL (SELECT {s_} AS g) r WHERE s.{c} IS NOT NULL AND NOT ST_IsEmpty(r.g)").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, s_=s_, src=sdk.ident(t), c=sql.Identifier(col))
