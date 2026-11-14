from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import deg_per_m


@sdk.register
class NearLines(ToolPlugin):
    key, order, category, icon = "nearlines", 50, "proximity", "t-nearlines"
    level = "mid"
    title = "خطوط ارتباط در شعاع"
    description = "بین هر عارضه و همه‌ی عارضه‌های لایه‌ی دیگر که در شعاع مشخص هستند خط اتصال می‌کشد."
    inputs, output = ("لایه اول", "لایه دوم"), "خط ارتباط + فاصله"
    example = "ارتباط هر مدرسه با همه‌ی پارک‌های نزدیک‌تر از ۸۰۰ متر برای نمایش روی نقشه."
    columns = ("ستون‌های لایه اول", "distance_m", "geom")
    chart_hint = {"kind": "hist", "field": "distance_m"}
    params = (
        Param("layer", "layer", "لایه اول"),
        Param("other", "layer", "لایه دوم"),
        Param("distance", "number", "شعاع جست‌وجو", "فقط جفت‌های نزدیک‌تر از این", "800", unit="متر"),
    )

    def build(self, ctx):
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a)
        cb, sb, _ = sdk.geom_of(b)
        d = ctx.number("distance", 1, 50_000)
        ctx.guard(a, ca, 20_000, "لایه‌ی اول تا ۲۰٬۰۰۰ عارضه مجاز است.")
        ctx.guard(b, cb, 20_000, "لایه‌ی دوم تا ۲۰٬۰۰۰ عارضه مجاز است.")
        ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
        pre = sql.SQL("")
        if sb in (0, 4326):
            pre = sql.SQL("AND b.{cb} && ST_Expand({ga}, {d} * {k})").format(
                cb=sql.Identifier(cb), ga=ga, d=sql.Literal(d), k=deg_per_m(ga))
        return sql.SQL(
            "SELECT {attrs}round(ST_Distance({ga}::geography, {gb}::geography)::numeric, 1) AS distance_m, "
            "ST_MakeLine(ST_PointOnSurface({ga}::geometry), ST_PointOnSurface({gb}::geometry)) AS geom "
            "FROM {A} a JOIN {B} b ON b.{cb} IS NOT NULL {pre} AND ST_DWithin({ga}::geography, {gb}::geography, {d}) "
            "WHERE a.{ca} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, a, "a"), ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b),
            cb=sql.Identifier(cb), ca=sql.Identifier(ca), pre=pre, d=sql.Literal(d))
