from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Dedupe(ToolPlugin):
    key, order, category, icon = "dedupe", 20, "quality", "t-dedupe"
    level = "mid"
    title = "حذف عارضه‌های تکراری"
    description = "عارضه‌هایی که هندسه‌ی یکسان دارند (و اختیاری مقدار یکسان در یک ستون) را به یکی تقلیل می‌دهد و تعداد تکرار را می‌نویسد."
    inputs, output = ("هر لایه",), "عارضه‌های یکتا + تعداد تکرار"
    example = "حذف نقطه‌های دوبار ثبت‌شده‌ی یک ایستگاه در داده‌ی ورودی."
    columns = ("ستون‌های لایه ورودی", "dup_count", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("field", "text", "ستون مقایسه", "اختیاری؛ فقط وقتی این ستون هم برابر باشد تکراری است", required=False, placeholder="name"),
        Param("tolerance", "number", "تلرانس مکانی", "نقطه‌های نزدیک‌تر از این یکسان حساب می‌شوند (۰ = دقیقاً یکسان)", "0",
              required=False, unit="متر", group="advanced"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        f = ctx.column("field", t)
        tol = ctx.number("tolerance", 0, 100) if (ctx.params.get("tolerance") or "").strip() else 0.0
        ctx.guard(t, col, 500_000, "این ابزار تا ۵۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        g = sdk.geom4326("s", col, srid)
        step = max(tol / 111_320.0, 1e-9)
        fv = sql.SQL("coalesce(s.{}::text, '')").format(sql.Identifier(f)) if f else sql.SQL("''")
        return sql.SQL(
            "SELECT DISTINCT ON (d._k) {dattrs}d._n AS dup_count, d._g AS geom FROM (SELECT s.*, {g}::geometry AS _g, "
            "md5(ST_AsBinary(ST_SnapToGrid({g}, {step}))::text || {fv}) AS _k, "
            "count(*) OVER (PARTITION BY md5(ST_AsBinary(ST_SnapToGrid({g}, {step}))::text || {fv})) AS _n "
            "FROM {src} s WHERE s.{c} IS NOT NULL) d ORDER BY d._k").format(
            dattrs=sdk.attr_sql(ctx.ex, t, "d"), g=g, step=sql.Literal(step), fv=fv, src=sdk.ident(t), c=sql.Identifier(col))
