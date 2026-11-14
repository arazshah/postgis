from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Snap(ToolPlugin):
    key, order, category, icon = "snap", 30, "quality", "t-snap"
    level = "mid"
    title = "چسباندن نقطه به خط"
    description = "نقطه‌ها را در شعاع مشخص به نزدیک‌ترین نقطه‌ی روی خط (یا مرز چندضلعی) منتقل می‌کند."
    inputs, output = ("لایه نقطه‌ای", "لایه خطی یا چندضلعی"), "نقطه‌های چسبیده + مقدار جابه‌جایی"
    example = "قرار دادن آدرس‌ها یا تصادفات روی محور خیابان در حداکثر ۳۰ متر."
    columns = ("ستون‌های لایه نقطه‌ای", "snapped", "moved_m", "geom")
    params = (
        Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
        Param("other", "layer", "لایه خطی یا چندضلعی هدف", "مثلاً خیابان‌ها"),
        Param("distance", "number", "حداکثر فاصله‌ی چسباندن", "نقطه‌های دورتر دست‌نخورده می‌مانند", "30", unit="متر"),
    )

    def build(self, ctx):
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a, ("POINT",), ctx.ex)
        cb, sb, _ = sdk.geom_of(b)
        d = ctx.number("distance", 0.1, 10_000)
        ctx.guard(a, ca, 100_000, "این ابزار تا ۱۰۰٬۰۰۰ نقطه را پشتیبانی می‌کند.")
        ga = sdk.geom4326("a", ca, sa)
        gab = sql.SQL("ST_Transform({}, {})").format(ga, sql.Literal(sb)) if sb not in (0, 4326) else ga
        return sql.SQL(
            "SELECT {attrs}coalesce(n.dist <= {d}, false) AS snapped, round((CASE WHEN n.dist <= {d} THEN n.dist ELSE 0 END)::numeric, 2) AS moved_m, "
            "CASE WHEN n.dist <= {d} THEN n.cp ELSE {ga}::geometry END AS geom FROM {A} a LEFT JOIN LATERAL "
            "(SELECT ST_ClosestPoint({gb}, {ga}) AS cp, ST_Distance({gb}::geography, {ga}::geography) AS dist FROM {B} b "
            "WHERE b.{cb} IS NOT NULL ORDER BY b.{cb} <-> {gab} LIMIT 1) n ON true WHERE a.{ca} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, a, "a"), d=sql.Literal(d), ga=ga, gb=sdk.geom4326("b", cb, sb), gab=gab,
            A=sdk.ident(a), B=sdk.ident(b), cb=sql.Identifier(cb), ca=sql.Identifier(ca))
