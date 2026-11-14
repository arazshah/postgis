from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Buffer(ToolPlugin):
    key, order, category, icon = "buffer", 10, "proximity", "t-buffer"
    popular = True
    title = "حریم (بافر)"
    description = "دور هر عارضه حریمی به فاصله دلخواه می‌کشد؛ مثلاً حریم ۵۰۰ متری ایستگاه‌ها."
    inputs, output = ("هر لایه",), "چندضلعی حریم"
    example = "حریم ۵۰۰ متری ایستگاه‌های مترو را بساز تا ببینی کدام مدرسه‌ها داخلش هستند."
    columns = ("ستون‌های لایه ورودی", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("distance", "number", "فاصله‌ی حریم", "فاصله‌ی حریم از هر عارضه", "500", unit="متر"),
        Param("dissolve", "bool", "همه حریم‌ها یکی شوند", "به‌جای یک حریم برای هر عارضه، یک چندضلعی واحد", required=False),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        d = ctx.number("distance", 1, 100_000)
        attrs = sdk.attrs(ctx.ex, t, "s")
        g = sdk.geom4326("s", col, srid)
        if ctx.params.get("dissolve") == "on":
            return sql.SQL("SELECT ST_Multi(ST_Union(ST_Buffer({g}::geography, {d})::geometry))::geometry(MultiPolygon, 4326)"
                           " AS geom FROM {src} s").format(g=g, d=sql.Literal(d), src=sdk.ident(t))
        return sql.SQL("SELECT {attrs}ST_Buffer({g}::geography, {d})::geometry(Polygon, 4326) AS geom "
                       "FROM {src} s WHERE s.{c} IS NOT NULL").format(
            attrs=sql.SQL(", ").join(attrs) + sql.SQL(", ") if attrs else sql.SQL(""), g=g, d=sql.Literal(d),
            src=sdk.ident(t), c=sql.Identifier(col))
