from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin

from ._network import vertex_join

CAP_FROM, CAP_TO = 3000, 500


@sdk.register
class NetNearest(ToolPlugin):
    key, order, category, icon = "netnearest", 30, "network", "t-netnearest"
    level = "mid"
    title = "نزدیک‌ترین روی شبکه"
    description = "برای هر نقطه نزدیک‌ترین مرکز را با فاصله‌ی واقعی روی خیابان‌ها پیدا می‌کند."
    inputs, output = ("نقاط مبدأ", "نقاط مقصد"), "همان نقاط + فاصله روی خیابان"
    example = "هر خانه تا نزدیک‌ترین درمانگاه چند متر راه دارد (نه فاصله مستقیم)."
    columns = ("ستون‌های لایه مبدأ", "network_m", "nearest_name (اختیاری)", "geom")
    needs_routing = True
    chart_hint = {"kind": "hist", "field": "network_m", "cumulative": "1"}
    params = (
        Param("layer", "layer", "لایه مبدأ", "مثلاً خانه‌ها یا مدرسه‌ها (حداکثر ۳۰۰۰ نقطه)", geom="point"),
        Param("other", "layer", "لایه مقصد", "مثلاً درمانگاه‌ها (حداکثر ۵۰۰ نقطه)", geom="point"),
        Param("label", "text", "ستون نام در لایه مقصد", "اختیاری؛ برای نوشتن نام نزدیک‌ترین", required=False, placeholder="name"),
        Param("distance", "number", "حداکثر فاصله روی شبکه", "نقطه‌هایی که دورتر باشند بدون مقدار می‌مانند", "5000", unit="متر"),
    )

    def build(self, ctx):
        ident, ex = sql.Identifier, ctx.ex
        ctx.need_routing()
        a = ctx.table("layer")
        ca, sa, _ = sdk.geom_of(a, ("POINT",), ex)
        b = ctx.table("other")
        cb, sb, _ = sdk.geom_of(b, ("POINT",), ex)
        label = ctx.params.get("label") or ""
        if label and label not in ctx.cols(b):
            raise ToolError("ستون نام لایه دوم نامعتبر است.")
        dist = ctx.number("distance", 50, 50_000)
        ctx.guard(a, ca, CAP_FROM, f"این ابزار تا {CAP_FROM} نقطه مبدأ را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        ctx.guard(b, cb, CAP_TO, f"این ابزار تا {CAP_TO} مرکز مقصد را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        gb = sdk.geom4326("b", cb, sb)
        lbl_t = sql.SQL(", b.{}::text AS lbl").format(ident(label)) if label else sql.SQL("")
        return sql.SQL(
            "WITH o AS (SELECT {attrs}{ga}::geometry AS g, v.id AS vid FROM {A} a {vertex} WHERE a.{ca} IS NOT NULL), "
            "t AS (SELECT DISTINCT ON (v.id) v.id AS vid{lbl_t} FROM {B} b CROSS JOIN LATERAL (SELECT id FROM routing.ways_vertices_pgr "
            "ORDER BY the_geom <-> {gb} LIMIT 1) v WHERE b.{cb} IS NOT NULL), "
            "near AS (SELECT DISTINCT ON (start_vid) start_vid, end_vid, dist FROM ("
            "SELECT start_vid, end_vid, max(agg_cost) AS dist FROM pgr_dijkstraNear({edges}, "
            "(SELECT array_agg(DISTINCT vid) FROM o), (SELECT array_agg(vid) FROM t), directed := true, cap := 1, global := false) "
            "GROUP BY start_vid, end_vid "
            "UNION ALL SELECT o2.vid, t.vid, 0 FROM (SELECT DISTINCT vid FROM o) o2 JOIN t ON t.vid = o2.vid) u "
            "ORDER BY start_vid, dist) "
            "SELECT {oattrs}round(n.dist::numeric, 1) AS network_m{lbl_out}, o.g AS geom FROM o "
            "LEFT JOIN near n ON n.start_vid = o.vid AND n.dist <= {dist} LEFT JOIN t ON t.vid = n.end_vid").format(
            attrs=sdk.attr_sql(ex, a, "a"), ga=sdk.geom4326("a", ca, sa), A=sdk.ident(a), vertex=vertex_join(ca, sa),
            ca=ident(ca), lbl_t=lbl_t, B=sdk.ident(b), gb=gb, cb=ident(cb), edges=sql.SQL(sdk.EDGES),
            oattrs=sdk.attr_sql(ex, a, "o"), lbl_out=sql.SQL(", t.lbl AS nearest_name") if label else sql.SQL(""),
            dist=sql.Literal(dist))
