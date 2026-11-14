from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._network import vertex_join

CAP = 200


@sdk.register
class OdMatrix(ToolPlugin):
    key, order, category, icon = "odmatrix", 50, "network", "t-odmatrix"
    level = "adv"
    title = "ماتریس مبدأ و مقصد"
    description = "فاصله‌ی واقعی روی خیابان‌ها بین همه‌ی جفت‌های مبدأ و مقصد را حساب می‌کند و با فاصله‌ی مستقیم مقایسه می‌کند (هر نقطه به نزدیک‌ترین رأس شبکه وصل می‌شود)."
    inputs, output = ("نقاط مبدأ", "نقاط مقصد"), "خط‌های مبدأ–مقصد + فاصله‌ی شبکه‌ای"
    example = "فاصله‌ی ۱۰۰ مدرسه تا ۲۰ درمانگاه روی شبکه‌ی معابر برای تحلیل دسترسی."
    columns = ("origin_id", "dest_id", "network_m", "straight_m", "detour", "geom")
    needs_routing = True
    params = (
        Param("layer", "layer", "لایه مبدأ", f"حداکثر {CAP} نقطه", geom="point"),
        Param("other", "layer", "لایه مقصد", f"حداکثر {CAP} نقطه", geom="point"),
        Param("distance", "number", "حداکثر فاصله‌ی شبکه‌ای", "جفت‌های دورتر در نتیجه نمی‌آیند", "10000", unit="متر"),
    )

    def build(self, ctx):
        ctx.need_routing()
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a, ("POINT",), ctx.ex)
        cb, sb, _ = sdk.geom_of(b, ("POINT",), ctx.ex)
        d = ctx.number("distance", 50, 100_000)
        ctx.guard(a, ca, CAP, f"این ابزار تا {CAP} نقطه‌ی مبدأ را پشتیبانی می‌کند.")
        ctx.guard(b, cb, CAP, f"این ابزار تا {CAP} نقطه‌ی مقصد را پشتیبانی می‌کند.")
        ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
        return sql.SQL(
            "WITH o AS (SELECT row_number() OVER () AS oid, {ga}::geometry AS g, v.id AS vid FROM {A} a {va} WHERE a.{ca} IS NOT NULL), "
            "t AS (SELECT row_number() OVER () AS tid, {gb}::geometry AS g, w.id AS vid FROM {B} b "
            "CROSS JOIN LATERAL (SELECT id FROM routing.ways_vertices_pgr ORDER BY the_geom <-> {gb} LIMIT 1) w WHERE b.{cb} IS NOT NULL), "
            "c AS (SELECT start_vid, end_vid, agg_cost FROM pgr_dijkstraCost({edges}, (SELECT array_agg(DISTINCT vid) FROM o), "
            "(SELECT array_agg(DISTINCT vid) FROM t), directed := true)) "
            "SELECT o.oid::int AS origin_id, t.tid::int AS dest_id, round(c.agg_cost::numeric, 1) AS network_m, "
            "round(ST_Distance(o.g::geography, t.g::geography)::numeric, 1) AS straight_m, "
            "round((c.agg_cost / NULLIF(ST_Distance(o.g::geography, t.g::geography), 0))::numeric, 2) AS detour, "
            "ST_MakeLine(o.g, t.g) AS geom FROM o JOIN c ON c.start_vid = o.vid JOIN t ON t.vid = c.end_vid "
            "WHERE c.agg_cost <= {d}").format(
            ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b), va=vertex_join(ca, sa), ca=sql.Identifier(ca), cb=sql.Identifier(cb),
            edges=sql.SQL(sdk.EDGES), d=sql.Literal(d))
