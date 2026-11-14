from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class SpatialJoin(ToolPlugin):
    key, order, category, icon = "spatialjoin", 60, "overlay", "t-spatialjoin"
    popular = True
    title = "پیوند مکانی صفات"
    description = "صفات چندضلعیِ حاوی هر عارضه (مثلاً نام محله) را به همان عارضه می‌چسباند."
    inputs, output = ("لایه مقصد", "لایه چندضلعی"), "همان عارضه‌ها + صفات چندضلعی"
    example = "به هر مدرسه نام محله و منطقه‌اش را اضافه کن."
    columns = ("ستون‌های لایه مقصد", "j_… (صفات چندضلعی)", "geom")
    params = (
        Param("layer", "layer", "لایه‌ای که صفت می‌گیرد", "نقطه، خط یا چندضلعی"),
        Param("other", "layer", "لایه چندضلعیِ منبع صفات", "مثلاً محله‌ها", geom="polygon"),
        Param("relation", "choice", "رابطه‌ی مکانی", default="intersects", required=False,
              choices=(("intersects", "تلاقی"), ("within", "کاملاً داخل"))),
        Param("keep", "bool", "عارضه‌های بدون تطابق هم بمانند", "با صفات تهی", required=False),
    )

    def build(self, ctx):
        ex = ctx.ex
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a)
        cb, sb, _ = sdk.geom_of(b, ("POLYGON",), ex)
        ctx.guard(a, ca, 100_000, "این ابزار تا ۱۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        ga = sdk.geom4326("a", ca, sa)
        ain = sdk.in_srid("a", ca, sa, sb)
        rel = (sql.SQL("ST_Within({ain}, b.{cb})") if ctx.choice("relation", ("intersects", "within"), "intersects") == "within"
               else sql.SQL("ST_Intersects(b.{cb}, {ain})")).format(ain=ain, cb=sql.Identifier(cb))
        keep = ctx.params.get("keep") == "on"
        j = sdk.attrs(ex, b, "j", "j_")
        return sql.SQL(
            "SELECT {attrs}{jattrs}{ga}::geometry AS geom FROM {A} a {join} JOIN LATERAL (SELECT b.* FROM {B} b "
            "WHERE b.{cb} IS NOT NULL AND {rel} LIMIT 1) j ON true WHERE a.{ca} IS NOT NULL").format(
            attrs=sdk.attr_sql(ex, a, "a"), jattrs=(sql.SQL(", ").join(j) + sql.SQL(", ")) if j else sql.SQL(""), ga=ga,
            A=sdk.ident(a), B=sdk.ident(b), join=sql.SQL("LEFT" if keep else "INNER"), cb=sql.Identifier(cb), rel=rel,
            ca=sql.Identifier(ca))

    def summary_extra(self, params):
        return ["همه بمانند"] if params.get("keep") == "on" else []
