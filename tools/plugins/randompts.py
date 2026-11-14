from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

CAP = 500_000


@sdk.register
class RandomPoints(ToolPlugin):
    key, order, category, icon = "randompts", 50, "aggregate", "t-randompts"
    level = "mid"
    title = "نقاط تصادفی در چندضلعی"
    description = "در هر چندضلعی تعداد مشخصی نقطه‌ی تصادفی (تکرارپذیر با seed ثابت) می‌گذارد."
    inputs, output = ("لایه چندضلعی",), "نقطه‌های تصادفی + شماره"
    example = "طرح نمونه‌برداری تصادفی ۲۰ نقطه در هر قطعه‌ی کشاورزی."
    columns = ("ستون‌های چندضلعی", "pt_no", "geom")
    params = (
        Param("layer", "layer", "لایه چندضلعی", geom="polygon"),
        Param("count", "number", "تعداد نقطه در هر چندضلعی", "", "10", unit="نقطه"),
        Param("seed", "number", "عدد تصادفی‌ساز (seed)", "با seed ثابت، نتیجه هر بار یکسان است", "1", required=False, group="advanced"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POLYGON",), ctx.ex)
        n = int(ctx.number("count", 1, 1000))
        seed = int(ctx.number("seed", 1, 1_000_000)) if (ctx.params.get("seed") or "").strip() else 1
        ctx.guards.append((sql.SQL("SELECT count(*) * {n} FROM (SELECT 1 FROM {src} s WHERE s.{c} IS NOT NULL LIMIT {lim}) x").format(
            n=sql.Literal(n), src=sdk.ident(t), c=sql.Identifier(col), lim=sql.Literal(CAP + 1)), CAP,
            "مجموع نقطه‌ها از ۵۰۰٬۰۰۰ بیشتر می‌شود؛ تعداد یا چندضلعی‌ها را کم کنید."))
        return sql.SQL(
            "SELECT {attrs}d.path[1] AS pt_no, d.geom AS geom FROM {src} s CROSS JOIN LATERAL "
            "ST_Dump(ST_GeneratePoints(ST_MakeValid({g}), {n}, {seed})) d WHERE s.{c} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, t, "s"), g=sdk.geom4326("s", col, srid), n=sql.Literal(n), seed=sql.Literal(seed),
            src=sdk.ident(t), c=sql.Identifier(col))
