from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class SelfOverlap(ToolPlugin):
    key, order, category, icon = "selfoverlap", 40, "quality", "t-selfoverlap"
    level = "mid"
    title = "یافتن همپوشانی درون‌لایه‌ای"
    description = "بخش‌هایی را که چندضلعی‌های یک لایه روی هم افتاده‌اند پیدا می‌کند؛ نشانه‌ی خطا در کاداستر یا پهنه‌بندی."
    inputs, output = ("لایه چندضلعی",), "ناحیه‌های همپوشان + مساحت"
    example = "پلاک‌هایی که در داده‌ی ثبتی روی هم افتاده‌اند."
    columns = ("a_label", "b_label", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه چندضلعی", geom="polygon"),
        Param("label", "text", "ستون شناسه یا نام", "اختیاری؛ برای دانستن کدام دو عارضه هم‌پوشانند", required=False, placeholder="name"),
        Param("min_area", "number", "کمینه‌ی مساحت همپوشانی", "همپوشانی‌های کوچک‌تر نادیده گرفته می‌شود", "1", unit="متر مربع",
              required=False, group="advanced"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POLYGON",), ctx.ex)
        label = ctx.column("label", t)
        mn = ctx.number("min_area", 0, 1e9) if (ctx.params.get("min_area") or "").strip() else 1.0
        ctx.guard(t, col, 20_000, "این ابزار تا ۲۰٬۰۰۰ چندضلعی را پشتیبانی می‌کند.")
        ga, gb = sdk.geom4326("a", col, srid), sdk.geom4326("b", col, srid)
        lbl = (sql.SQL("a.{l}::text AS a_label, b.{l}::text AS b_label, ").format(l=sql.Identifier(label)) if label
               else sql.SQL(""))
        return sql.SQL(
            "SELECT {lbl}round(ST_Area(x.g::geography)::numeric, 1) AS area_m2, x.g AS geom FROM {A} a JOIN {A} b "
            "ON a.ctid < b.ctid AND a.{c} IS NOT NULL AND b.{c} IS NOT NULL AND a.{c} && b.{c} "
            "CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_Intersection(ST_MakeValid({ga}), ST_MakeValid({gb})), 3) AS g) x "
            "WHERE NOT ST_IsEmpty(x.g) AND ST_Area(x.g::geography) >= {mn}").format(
            lbl=lbl, A=sdk.ident(t), c=sql.Identifier(col), ga=ga, gb=gb, mn=sql.Literal(mn))
