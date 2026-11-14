from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Dissolve(ToolPlugin):
    key, order, category, icon = "dissolve", 40, "geometry", "t-dissolve"
    popular = True
    title = "یکپارچه‌سازی بر اساس ستون"
    description = "عارضه‌هایی را که مقدار یکسانی در یک ستون دارند به یک عارضه تبدیل می‌کند (ادغام)."
    inputs, output = ("هر لایه",), "یک عارضه برای هر مقدار + تعداد"
    example = "ادغام محله‌ها به مناطق شهرداری بر اساس ستون «منطقه»."
    columns = ("ستون گروه‌بندی", "feature_count", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("field", "text", "ستون گروه‌بندی", "خالی = همه‌ی عارضه‌ها یکی شوند", required=False, placeholder="district"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        field = ctx.column("field", t)
        ctx.guard(t, col, 100_000, "این ابزار تا ۱۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        u = sql.SQL("ST_Union(ST_MakeValid({}))").format(sdk.geom4326("s", col, srid))
        tail = sql.SQL("FROM {src} s WHERE s.{c} IS NOT NULL").format(src=sdk.ident(t), c=sql.Identifier(col))
        if field:
            f = sql.Identifier(field)
            return sql.SQL("SELECT s.{f}, count(*) AS feature_count, {u} AS geom {tail} GROUP BY s.{f}").format(f=f, u=u, tail=tail)
        return sql.SQL("SELECT count(*) AS feature_count, {u} AS geom {tail}").format(u=u, tail=tail)

    def summary_extra(self, params):
        return [f"بر اساس {params['field']}"] if params.get("field") else []
