from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._network import vertex_join

CAP = 500


@sdk.register
class Coverage(ToolPlugin):
    key, order, category, icon = "coverage", 160, "network", "t-coverage"
    title = "پوشش چند مرکز"
    description = "حوزه‌ی دسترسی روی شبکه معابر را برای همه‌ی نقطه‌های یک لایه می‌سازد و هر بخش را به نزدیک‌ترین مرکز می‌دهد."
    inputs, output = ("نقاط مرکز",), "حوزه دسترسی هر مرکز"
    example = "پوشش ۸۰۰ متری پیاده‌ی همه‌ی ایستگاه‌های مترو؛ هر بخش به نزدیک‌ترین ایستگاه تعلق دارد."
    columns = ("ستون‌های لایه مرکز", "distance_m", "edges", "geom")
    needs_routing = True
    params = (
        Param("layer", "layer", "لایه مراکز", "مثلاً ایستگاه‌ها (حداکثر ۵۰۰ نقطه)", geom="point"),
        Param("distance", "number", "فاصله روی شبکه معابر (متر)", default="800"),
    )

    def build(self, ctx):
        ident, ex = sql.Identifier, ctx.ex
        ctx.need_routing()
        a = ctx.table("layer")
        ca, sa, _ = sdk.geom_of(a, ("POINT",), ex)
        dist = ctx.number("distance", 50, 50_000)
        ctx.guard(a, ca, CAP, f"پوشش چند مرکز تا {CAP} نقطه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        return sql.SQL(
            "WITH o AS (SELECT {attrs}v.id AS vid FROM {A} a {vertex} WHERE a.{ca} IS NOT NULL), "
            "d AS (SELECT * FROM pgr_drivingDistance({edges}, (SELECT array_agg(DISTINCT vid) FROM o), {dist}, true, true)), "
            "h AS (SELECT d.start_vid, count(*) AS edges, ST_ConcaveHull(ST_Collect(w.the_geom), 0.3) AS hull "
            "FROM d JOIN routing.ways w ON w.gid = d.edge GROUP BY d.start_vid) "
            "SELECT {oattrs}{dist}::int AS distance_m, h.edges, CASE WHEN GeometryType(h.hull) = 'POLYGON' THEN h.hull "
            "ELSE ST_Buffer(h.hull::geography, 20)::geometry END AS geom FROM o JOIN h ON h.start_vid = o.vid").format(
            attrs=sdk.attr_sql(ex, a, "a"), A=sdk.ident(a), vertex=vertex_join(ca, sa), ca=ident(ca),
            edges=sql.SQL(sdk.EDGES), dist=sql.Literal(dist), oattrs=sdk.attr_sql(ex, a, "o"))
