from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._overlay import mask_sql


@sdk.register
class Clip(ToolPlugin):
    key, order, category, icon = "clip", 10, "overlay", "t-clip"
    popular = True
    title = "برش با مرز"
    description = "هر لایه‌ای را با یک مرز چندضلعی می‌بُرد و فقط بخش داخل مرز را نگه می‌دارد."
    inputs, output = ("هر لایه", "مرز چندضلعی"), "بخش داخل مرز"
    example = "معابر فقط داخل منطقه ۶، یا مدرسه‌های داخل یک شهرستان."
    columns = ("ستون‌های لایه ورودی", "geom")
    params = (
        Param("layer", "layer", "لایه‌ای که بریده شود", "نقطه، خط یا چندضلعی"),
        Param("other", "layer", "مرز برش", "مثلاً منطقه شهرداری", geom="polygon"),
    )

    def build(self, ctx):
        ident, ex = sql.Identifier, ctx.ex
        a, q = ctx.table("layer"), ctx.table("other")
        ca, sa, ta = sdk.geom_of(a, ("POINT", "LINE", "POLYGON"), ex)
        cq, sq, _ = sdk.geom_of(q, ("POLYGON",), ex)
        ga = sdk.geom4326("a", ca, sa)
        kinds = sdk.base_kinds(ta.upper())
        res = sql.SQL("ST_Intersection(ST_MakeValid({ga}), m.g)").format(ga=ga)
        if len(kinds) == 1:
            res = sql.SQL("ST_CollectionExtract({}, {})").format(res, sql.Literal({"POINT": 1, "LINESTRING": 2, "POLYGON": 3}[kinds[0]]))
        return mask_sql(q, cq, sq) + sql.SQL(
            "SELECT {attrs}c.g AS geom FROM {A} a CROSS JOIN m CROSS JOIN LATERAL (SELECT {res} AS g) c "
            "WHERE a.{ca} IS NOT NULL AND m.g IS NOT NULL {pre} AND ST_Intersects({ga}, m.g) AND NOT ST_IsEmpty(c.g)").format(
            attrs=sdk.attr_sql(ex, a, "a"), A=sdk.ident(a), res=res, ca=ident(ca), ga=ga,
            pre=sdk.bbox_pre("a", ca, sa, sql.SQL("m.g")))
