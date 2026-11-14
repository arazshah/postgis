from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class SdEllipse(ToolPlugin):
    key, order, category, icon = "sdellipse", 20, "stats", "t-sdellipse"
    level = "adv"
    title = "بیضی انحراف معیار"
    description = "بیضی‌ای که جهت و گستره‌ی غالب پراکندگی نقطه‌ها را نشان می‌دهد (۱، ۲ یا ۳ انحراف معیار)."
    inputs, output = ("لایه نقطه‌ای",), "یک بیضی + قطرها و زاویه"
    example = "جهت غالب گسترش تصادفات یا آتش‌سوزی‌ها در شهر."
    columns = ("n", "major_m", "minor_m", "angle_deg", "geom")
    params = (
        Param("layer", "layer", "لایه نقطه‌ای", geom="point"),
        Param("k", "choice", "اندازه‌ی بیضی", default="1", required=False,
              choices=(("1", "۱ انحراف معیار (۶۸٪)"), ("2", "۲ انحراف معیار (۹۵٪)"), ("3", "۳ انحراف معیار (۹۹٪)"))),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t, ("POINT",), ctx.ex)
        k = int(ctx.choice("k", ("1", "2", "3"), "1"))
        ctx.guard(t, col, 500_000, "این ابزار تا ۵۰۰٬۰۰۰ نقطه را پشتیبانی می‌کند.")
        return sql.SQL(
            "WITH p AS (SELECT ST_X(q.t) AS x, ST_Y(q.t) AS y FROM {src} s CROSS JOIN LATERAL (SELECT ST_Transform({g}, 3857) AS t) q "
            "WHERE s.{c} IS NOT NULL), "
            "c AS (SELECT count(*) AS n, avg(x) AS mx, avg(y) AS my, var_pop(x) AS sxx, var_pop(y) AS syy, covar_pop(x, y) AS sxy FROM p), "
            "e AS (SELECT n, mx, my, (sxx + syy) / 2 + sqrt(((sxx - syy) / 2) ^ 2 + sxy ^ 2) AS l1, "
            "(sxx + syy) / 2 - sqrt(((sxx - syy) / 2) ^ 2 + sxy ^ 2) AS l2, 0.5 * atan2(2 * sxy, sxx - syy) AS phi FROM c), "
            "z AS (SELECT e.*, cos(radians(ST_Y(ST_Transform(ST_SetSRID(ST_MakePoint(mx, my), 3857), 4326)))) AS kc FROM e) "
            "SELECT n, round((2 * {k} * sqrt(l1) * kc)::numeric, 1) AS major_m, round((2 * {k} * sqrt(l2) * kc)::numeric, 1) AS minor_m, "
            "round(mod(mod(degrees(pi() / 2 - phi)::numeric, 180) + 180, 180), 1) AS angle_deg, "
            "ST_Transform(ST_Translate(ST_Rotate(ST_Scale(ST_Buffer(ST_SetSRID(ST_MakePoint(0, 0), 3857), 1, 'quad_segs=24'), "
            "ST_MakePoint({k} * sqrt(l1), {k} * sqrt(l2))), phi, ST_SetSRID(ST_MakePoint(0, 0), 3857)), mx, my), 4326) AS geom "
            "FROM z WHERE n >= 3 AND l2 > 0").format(g=sdk.geom4326("s", col, srid), src=sdk.ident(t), c=sql.Identifier(col),
                                                     k=sql.Literal(k))

    def after_create(self, conn, target):
        if conn.execute(sql.SQL("SELECT count(*) FROM {}").format(target)).fetchone()[0] == 0:
            raise ToolError("برای ساخت بیضی دست‌کم ۳ نقطه‌ی غیرهم‌خط لازم است.")
