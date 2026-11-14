from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

MODES = ("convex", "concave", "each")


@sdk.register
class Hull(ToolPlugin):
    key, order, category, icon = "hull", 20, "geometry", "t-hull"
    level = "mid"
    title = "پوسته‌ی محدب و مقعر"
    description = "کوچک‌ترین پوسته‌ای که دور همه‌ی عارضه‌ها (یا دور هر عارضه) کشیده می‌شود؛ محدب یا فشرده‌تر (مقعر)."
    inputs, output = ("هر لایه",), "یک چندضلعی پوسته + تعداد عارضه"
    example = "گستره‌ی واقعی پراکندگی نقاط تصادف با پوسته‌ی مقعر."
    columns = ("feature_count", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("mode", "choice", "نوع پوسته", default="convex", required=False,
              choices=(("convex", "محدب (همه)"), ("concave", "مقعر (همه)"), ("each", "محدب برای هر عارضه"))),
        Param("ratio", "number", "فشردگی پوسته‌ی مقعر", "۱ = محدب، نزدیک ۰ = بسیار فشرده", "0.3", group="advanced", required=False),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        mode = ctx.choice("mode", MODES, "convex")
        ctx.guard(t, col, 200_000, "این ابزار تا ۲۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        g = sdk.geom4326("s", col, srid)
        if mode == "each":
            return sql.SQL("SELECT {attrs}ST_ConvexHull({g}) AS geom FROM {src} s WHERE s.{c} IS NOT NULL").format(
                attrs=sdk.attr_sql(ctx.ex, t, "s"), g=g, src=sdk.ident(t), c=sql.Identifier(col))
        if mode == "concave":
            ratio = ctx.number("ratio", 0.01, 1)
            h = sql.SQL("ST_ConcaveHull(ST_Collect({g}), {r})").format(g=g, r=sql.Literal(ratio))
        else:
            h = sql.SQL("ST_ConvexHull(ST_Collect({g}))").format(g=g)
        return sql.SQL("SELECT h.n AS feature_count, round(ST_Area(h.g::geography)::numeric, 1) AS area_m2, h.g AS geom "
                       "FROM (SELECT count(*) AS n, {h} AS g FROM {src} s WHERE s.{c} IS NOT NULL) h "
                       "WHERE GeometryType(h.g) = 'POLYGON'").format(h=h, src=sdk.ident(t), c=sql.Identifier(col))
