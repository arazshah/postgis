from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import num_col

CAP = 3000


@sdk.register
class Hotspot(ToolPlugin):
    key, order, category, icon = "hotspot", 30, "stats", "t-hotspot"
    level = "adv"
    title = "کانون‌های داغ و سرد (Gi*)"
    description = "با آماره‌ی Getis-Ord Gi* خوشه‌های معنادار مقدارهای زیاد (داغ) و کم (سرد) را با سطح اطمینان پیدا می‌کند."
    inputs, output = ("نقطه یا چندضلعی با ستون عددی",), "همان عارضه‌ها + z و رده‌ی معناداری"
    example = "کانون‌های داغ قیمت زمین یا تعداد حوادث در محله‌ها."
    columns = ("ستون‌های لایه ورودی", "neighbors", "gi_z", "hotspot (hot99…cold99 | not_sig)", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی", "نقطه یا چندضلعی (حداکثر ۳۰۰۰ عارضه)"),
        Param("value", "text", "ستون عددی", "مقداری که می‌خواهید خوشه‌هایش را ببینید", placeholder="price"),
        Param("distance", "number", "شعاع همسایگی", "عارضه‌های نزدیک‌تر از این همسایه‌اند", "1000", unit="متر"),
    )

    def build(self, ctx):
        ex = ctx.ex
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        v = num_col(ctx, t, "value", required=True)
        d = ctx.number("distance", 1, 100_000)
        ctx.guard(t, col, CAP, f"این ابزار تا {CAP} عارضه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        g = sdk.geom4326("s", col, srid)
        vi = sql.Identifier(v)
        return sql.SQL(
            "WITH f AS (SELECT {attrs}s.{v}::float8 AS _x, ST_PointOnSurface({g}) AS _pt, {g}::geometry AS _g FROM {src} s "
            "WHERE s.{c} IS NOT NULL AND s.{v} IS NOT NULL), "
            "st AS (SELECT count(*)::float8 AS n, avg(_x) AS xb, stddev_pop(_x) AS sd FROM f), "
            "r AS (SELECT f.*, nb.m, nb.sx, st.n, st.xb, st.sd FROM f CROSS JOIN st CROSS JOIN LATERAL "
            "(SELECT count(*)::float8 AS m, sum(f2._x) AS sx FROM f f2 WHERE f2._pt && ST_Expand(f._pt, {d} / 111320.0 / "
            "greatest(cos(radians(ST_Y(f._pt))), 0.05)) AND ST_DWithin(f._pt::geography, f2._pt::geography, {d})) nb), "
            "z AS (SELECT r.*, (r.sx - r.xb * r.m) / NULLIF(r.sd * sqrt((r.n * r.m - r.m ^ 2) / NULLIF(r.n - 1, 0)), 0) AS gi FROM r) "
            "SELECT {zattrs}z.m::int AS neighbors, round(z.gi::numeric, 3) AS gi_z, "
            "CASE WHEN z.gi IS NULL THEN 'not_sig' WHEN z.gi >= 2.576 THEN 'hot99' WHEN z.gi >= 1.96 THEN 'hot95' WHEN z.gi >= 1.645 THEN 'hot90' "
            "WHEN z.gi <= -2.576 THEN 'cold99' WHEN z.gi <= -1.96 THEN 'cold95' WHEN z.gi <= -1.645 THEN 'cold90' ELSE 'not_sig' END AS hotspot, "
            "z._g AS geom FROM z").format(
            attrs=sdk.attr_sql(ex, t, "s"), v=vi, g=g, src=sdk.ident(t), c=sql.Identifier(col), d=sql.Literal(d),
            zattrs=sdk.attr_sql(ex, t, "z"))

    def summary_extra(self, params):
        return [f"ستون {params['value']}"] if params.get("value") else []
