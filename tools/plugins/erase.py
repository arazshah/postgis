from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._overlay import mask_sql


@sdk.register
class Erase(ToolPlugin):
    key, order, category, icon = "erase", 20, "overlay", "t-erase"
    title = "حذف ناحیه"
    description = "بخشی از لایه چندضلعی را که زیر لایه‌ی چندضلعی دیگر قرار دارد حذف می‌کند."
    inputs, output = ("چندضلعی", "چندضلعی حذفی"), "چندضلعی باقی‌مانده"
    example = "بخش‌هایی از شهر که بیرون حریم ۵۰۰ متری هر مدرسه‌اند؛ یعنی مناطق کم‌برخوردار."
    columns = ("ستون‌های لایه اول", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه‌ای که از آن حذف شود", "مثلاً مرز شهر", geom="polygon"),
        Param("other", "layer", "ناحیهٔ حذفی", "مثلاً حریم مدرسه‌ها", geom="polygon"),
    )

    def build(self, ctx):
        ex = ctx.ex
        a, q = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a, ("POLYGON",), ex)
        cq, sq, _ = sdk.geom_of(q, ("POLYGON",), ex)
        ga = sdk.geom4326("a", ca, sa)
        res = sql.SQL("ST_CollectionExtract(CASE WHEN m.g IS NOT NULL AND ST_Intersects({ga}, m.g) "
                      "THEN ST_Difference(ST_MakeValid({ga}), m.g) ELSE ST_MakeValid({ga}) END, 3)").format(ga=ga)
        return mask_sql(q, cq, sq) + sql.SQL(
            "SELECT {attrs}round(ST_Area(c.g::geography)::numeric, 1) AS area_m2, c.g AS geom FROM {A} a CROSS JOIN m "
            "CROSS JOIN LATERAL (SELECT {res} AS g) c WHERE a.{ca} IS NOT NULL AND NOT ST_IsEmpty(c.g)").format(
            attrs=sdk.attr_sql(ex, a, "a"), A=sdk.ident(a), res=res, ca=sql.Identifier(ca))
