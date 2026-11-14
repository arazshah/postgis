from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class LineCross(ToolPlugin):
    key, order, category, icon = "linecross", 30, "linear", "t-linecross"
    level = "mid"
    title = "نقاط تقاطع خطوط"
    description = "محل برخورد خط‌های یک لایه با هم (یا با لایه‌ی خطی دیگر) را به‌صورت نقطه استخراج می‌کند."
    inputs, output = ("لایه خطی", "لایه خطی دوم (اختیاری)"), "نقطه‌های تقاطع"
    example = "چهارراه‌ها و تقاطع‌های شبکه‌ی خیابان، یا نقاط برخورد رودخانه با جاده."
    columns = ("geom",)
    params = (
        Param("layer", "layer", "لایه خطی", geom="line"),
        Param("other", "layer", "لایه خطی دوم", "خالی = تقاطع خط‌های همین لایه با هم", required=False, geom="line", empty="همان لایه‌ی اول"),
    )

    def build(self, ctx):
        a = ctx.table("layer")
        ca, sa, _ = sdk.geom_of(a, ("LINE",), ctx.ex)
        ctx.guard(a, ca, 20_000, "لایه‌ی اول تا ۲۰٬۰۰۰ خط مجاز است.")
        other = ctx.params.get("other") or ""
        b = ctx.table("other") if other else a
        cb, sb, _ = sdk.geom_of(b, ("LINE",), ctx.ex)
        if other:
            ctx.guard(b, cb, 20_000, "لایه‌ی دوم تا ۲۰٬۰۰۰ خط مجاز است.")
        ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
        pair = sql.SQL("a.ctid < b.ctid") if not other else sql.SQL("true")
        return sql.SQL(
            "SELECT DISTINCT ON (ST_AsBinary(p.geom)) p.geom AS geom FROM {A} a JOIN {B} b ON a.{ca} IS NOT NULL AND b.{cb} IS NOT NULL "
            "AND {pair} AND ST_Intersects(b.{cb}, {ain}) CROSS JOIN LATERAL ST_Dump(ST_CollectionExtract("
            "ST_Intersection({ga}, {gb}), 1)) p").format(
            A=sdk.ident(a), B=sdk.ident(b), ca=sql.Identifier(ca), cb=sql.Identifier(cb), pair=pair,
            ain=sdk.in_srid("a", ca, sa, sb), ga=ga, gb=gb)
