from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Measure(ToolPlugin):
    key, order, category, icon = "measure", 110, "aggregate", "t-measure"
    title = "طول و مساحت در چندضلعی"
    description = "مجموع طول خط‌ها یا مساحت چندضلعی‌های یک لایه را داخل هر چندضلعی حساب می‌کند."
    inputs, output = ("چندضلعی", "خط یا چندضلعی"), "چندضلعی‌ها + طول یا مساحت"
    example = "کیلومتر معبر در هر محله، یا مساحت فضای سبز هر منطقه."
    columns = ("ستون‌های چندضلعی", "length_m + km_per_km2", "یا area_m2 + share_pct")
    params = (
        Param("layer", "layer", "لایه چندضلعی", "مثلاً محله‌ها", geom="polygon"),
        Param("other", "layer", "لایه‌ای که اندازه‌گیری شود", "خطی برای طول، چندضلعی برای مساحت"),
        Param("mode", "choice", "اندازه‌گیری", default="length", required=False,
              choices=(("length", "طول خط‌ها"), ("area", "مساحت چندضلعی‌ها"))),
    )

    def build(self, ctx):
        ident, ex = sql.Identifier, ctx.ex
        p, q = ctx.table("layer"), ctx.table("other")
        mode = "area" if ctx.params.get("mode") == "area" else "length"
        cp, sp, _ = sdk.geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = sdk.geom_of(q, ("POLYGON",) if mode == "area" else ("LINE",), ex)
        pg, qg = sdk.geom4326("p", cp, sp), sdk.geom4326("q", cq, sq)
        inter = sql.SQL("ST_CollectionExtract(ST_Intersection(ST_MakeValid({pg}), ST_MakeValid({qg})), {k})").format(
            pg=pg, qg=qg, k=sql.Literal(3 if mode == "area" else 2))
        if mode == "area":
            val = sql.SQL("coalesce(ST_Area(ST_Union({i})::geography), 0)").format(i=inter)
            out = sql.SQL("round(m.v::numeric, 1) AS area_m2, round((100 * m.v / NULLIF(ST_Area({pg}::geography), 0))::numeric, 2) "
                          "AS share_pct").format(pg=pg)
        else:
            val = sql.SQL("coalesce(sum(ST_Length({i}::geography)), 0)").format(i=inter)
            out = sql.SQL("round(m.v::numeric, 1) AS length_m, round((m.v / 1000.0 / NULLIF(ST_Area({pg}::geography) / 1e6, 0))::numeric, 3) "
                          "AS km_per_km2").format(pg=pg)
        return sql.SQL(
            "SELECT {attrs}{out}, {pg} AS geom FROM {P} p CROSS JOIN LATERAL (SELECT {val} AS v FROM {Q} q "
            "WHERE q.{cq} IS NOT NULL AND ST_Intersects(p.{cp}, {gq})) m WHERE p.{cp} IS NOT NULL").format(
            attrs=sdk.attr_sql(ex, p, "p"), out=out, pg=pg, val=val, P=sdk.ident(p), Q=sdk.ident(q),
            cp=ident(cp), cq=ident(cq), gq=sdk.in_srid("q", cq, sq, sp))

    def summary_extra(self, params):
        return ["مساحت" if params.get("mode") == "area" else "طول"]
