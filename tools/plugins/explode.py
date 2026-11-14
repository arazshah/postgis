from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Explode(ToolPlugin):
    key, order, category, icon = "explode", 50, "geometry", "t-explode"
    title = "تفکیک چندبخشی"
    description = "عارضه‌های چندبخشی (Multi) را به عارضه‌های تک‌بخشی جدا می‌شکند؛ صفات هر بخش حفظ می‌شود."
    inputs, output = ("هر لایه",), "یک ردیف برای هر بخش"
    example = "جدا کردن جزیره‌های یک استان چندبخشی برای محاسبه‌ی مساحت هر جزیره."
    columns = ("ستون‌های لایه ورودی", "part_no", "geom")
    params = (Param("layer", "layer", "لایه ورودی"),)

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        ctx.guard(t, col, 200_000, "این ابزار تا ۲۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        return sql.SQL("SELECT {attrs}d.path[1] AS part_no, d.geom AS geom FROM {src} s "
                       "CROSS JOIN LATERAL ST_Dump({g}) d WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col))
