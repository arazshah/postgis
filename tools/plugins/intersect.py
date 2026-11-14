from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Intersect(ToolPlugin):
    key, order, category, icon = "intersect", 30, "overlay", "t-intersect"
    level = "mid"
    title = "اشتراک دو لایه"
    description = "بخش مشترک دو لایه‌ی چندضلعی را می‌سازد و صفات هر دو لایه را کنار هم نگه می‌دارد."
    inputs, output = ("لایه چندضلعی اول", "لایه چندضلعی دوم"), "چندضلعی‌های مشترک + صفات هر دو"
    example = "تقاطع پهنه‌ی سیل با کاربری زمین: هر کاربری چه مساحتی در پهنه است؟"
    columns = ("a_… (صفات لایه اول)", "b_… (صفات لایه دوم)", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه چندضلعی اول", geom="polygon"),
        Param("other", "layer", "لایه چندضلعی دوم", geom="polygon"),
    )

    def build(self, ctx):
        ex = ctx.ex
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a, ("POLYGON",), ex)
        cb, sb, _ = sdk.geom_of(b, ("POLYGON",), ex)
        ctx.guard(a, ca, 20_000, "لایه‌ی اول تا ۲۰٬۰۰۰ چندضلعی مجاز است.")
        ctx.guard(b, cb, 20_000, "لایه‌ی دوم تا ۲۰٬۰۰۰ چندضلعی مجاز است.")
        ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
        at = sdk.attrs(ex, a, "a", "a_") + sdk.attrs(ex, b, "b", "b_")
        return sql.SQL(
            "SELECT {attrs}round(ST_Area(c.g::geography)::numeric, 1) AS area_m2, c.g AS geom FROM {A} a "
            "JOIN {B} b ON ST_Intersects(b.{cb}, {ain}) CROSS JOIN LATERAL "
            "(SELECT ST_CollectionExtract(ST_Intersection(ST_MakeValid({ga}), ST_MakeValid({gb})), 3) AS g) c "
            "WHERE a.{ca} IS NOT NULL AND b.{cb} IS NOT NULL AND NOT ST_IsEmpty(c.g)").format(
            attrs=sql.SQL(", ").join(at) + sql.SQL(", ") if at else sql.SQL(""), A=sdk.ident(a), B=sdk.ident(b),
            cb=sql.Identifier(cb), ca=sql.Identifier(ca), ain=sdk.in_srid("a", ca, sa, sb), ga=ga, gb=gb)
