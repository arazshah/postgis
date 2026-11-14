from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import num_col


@sdk.register
class MeanCenter(ToolPlugin):
    key, order, category, icon = "meancenter", 10, "stats", "t-meancenter"
    level = "mid"
    title = "مرکز میانگین و فاصله‌ی استاندارد"
    description = "مرکز ثقل پراکندگی نقطه‌ها (با وزن اختیاری) و فاصله‌ی استاندارد آن؛ برای هر گروه جداگانه هم ممکن است."
    inputs, output = ("لایه نقطه‌ای",), "نقطه‌ی مرکز + فاصله‌ی استاندارد"
    example = "مرکز ثقل جمعیت هر شهرستان با وزن ستون «جمعیت»."
    columns = ("ستون گروه (اختیاری)", "n", "std_distance_m", "geom")
    params = (
        Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
        Param("weight", "text", "ستون وزن", "اختیاری؛ ستون عددی", required=False, placeholder="population"),
        Param("field", "text", "ستون گروه‌بندی", "اختیاری؛ برای هر مقدار یک مرکز", required=False, placeholder="city", group="advanced"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POINT",), ctx.ex)
        w = num_col(ctx, t, "weight")
        f = ctx.column("field", t)
        ctx.guard(t, col, 500_000, "این ابزار تا ۵۰۰٬۰۰۰ نقطه را پشتیبانی می‌کند.")
        wexpr = sql.SQL("greatest(s.{}::float8, 0)").format(sql.Identifier(w)) if w else sql.SQL("1.0")
        gexpr = sql.SQL("s.{}").format(sql.Identifier(f)) if f else sql.SQL("NULL::text")
        gcol = sql.SQL("c.grp AS {}, ").format(sql.Identifier(f)) if f else sql.SQL("")
        return sql.SQL(
            "WITH p AS (SELECT {gexpr} AS grp, ST_X(q.t) AS x, ST_Y(q.t) AS y, {w} AS w FROM {src} s "
            "CROSS JOIN LATERAL (SELECT ST_Transform({g}, 3857) AS t) q WHERE s.{c} IS NOT NULL AND ({w}) > 0), "
            "c AS (SELECT grp, count(*) AS n, sum(w) AS sw, sum(w * x) / sum(w) AS mx, sum(w * y) / sum(w) AS my FROM p GROUP BY grp) "
            "SELECT {gcol}c.n, round((sqrt(sum(p.w * ((p.x - c.mx) ^ 2 + (p.y - c.my) ^ 2)) / c.sw) "
            "* cos(radians(ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(c.mx, c.my), 3857), 4326)))))::numeric, 1) AS std_distance_m, "
            "ST_Transform(ST_SetSRID(ST_MakePoint(c.mx, c.my), 3857), 4326) AS geom "
            "FROM c JOIN p ON p.grp IS NOT DISTINCT FROM c.grp GROUP BY c.grp, c.n, c.sw, c.mx, c.my").format(
            gexpr=gexpr, w=wexpr, g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col), gcol=gcol)
