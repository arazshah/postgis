from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import unary


@sdk.register
class Centroid(ToolPlugin):
    key, order, category, icon = "centroid", 10, "geometry", "t-centroid"
    title = "مرکز یا نقطه‌ی درون عارضه"
    description = "از هر عارضه یک نقطه می‌سازد: مرکز هندسی، یا نقطه‌ای که حتماً داخل چندضلعی بیفتد."
    inputs, output = ("هر لایه",), "نقطه برای هر عارضه"
    example = "نقطه‌ی برچسب هر محله، یا تبدیل چندضلعی ساختمان‌ها به نقطه."
    columns = ("ستون‌های لایه ورودی", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("mode", "choice", "نوع نقطه", default="surface", required=False,
              choices=(("surface", "نقطه‌ی درون عارضه"), ("centroid", "مرکز هندسی"))),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        fn = "ST_Centroid" if ctx.choice("mode", ("surface", "centroid"), "surface") == "centroid" else "ST_PointOnSurface"
        return unary(ctx, t, col, sql.SQL("{fn}({g})").format(fn=sql.SQL(fn), g=sdk.geom4326("s", col, srid)))
