from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class Overlap(ToolPlugin):
    key, order, category, icon = "overlap", 50, "overlay", "t-overlap"
    title = "سهم همپوشانی"
    description = "سهم هر دسته (مثلاً کاربری زمین) از مساحت هر چندضلعی (مثلاً محله) با برش دو لایه چندضلعی."
    inputs, output = ("چندضلعی منطقه", "چندضلعی دسته‌دار"), "سهم هر دسته در هر منطقه"
    example = "سهم هر کاربری زمین (مسکونی، تجاری…) از مساحت هر محله."
    columns = ("zone", "category", "area_m2", "share_pct")
    chart_hint = {"kind": "stacked", "field": "zone", "series": "category", "value": "area_m2", "agg": "sum", "percent": "1"}
    params = (
        Param("layer", "layer", "لایه مناطق", "مثلاً محله", geom="polygon"),
        Param("other", "layer", "لایه چندضلعی دسته‌دار", "مثلاً کاربری زمین", geom="polygon"),
        Param("zone", "text", "ستون نام مناطق (لایه اول)", placeholder="name"),
        Param("category", "text", "ستون دسته (لایه دوم)", placeholder="landuse"),
    )

    def build(self, ctx):
        ex, params = ctx.ex, ctx.params
        p, q = ctx.table("layer"), ctx.table("other")
        cp, sp, _ = sdk.geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = sdk.geom_of(q, ("POLYGON",), ex)
        cat, zone = (params.get("category") or "").strip(), (params.get("zone") or "").strip()
        if cat not in ctx.attr_cols(q):
            raise ToolError("ستون دسته (مثلاً کاربری) را از لایه دوم انتخاب کنید.")
        if zone not in ctx.attr_cols(p):
            raise ToolError("ستون نام یا شناسه چندضلعی‌ها (مثلاً نام محله) را از لایه اول انتخاب کنید.")
        pz, qz = sdk.geom4326("p", cp, sp), sdk.geom4326("q", cq, sq)
        return sql.SQL(
            "WITH j AS (SELECT p.ctid::text AS pid, p.{zone}::text AS zone, q.{cat}::text AS category, "
            "ST_Area(ST_MakeValid({pz})::geography) AS zone_area, i.g FROM {P} p JOIN {Q} q ON ST_Intersects(p.{cp}, {gq}) "
            "CROSS JOIN LATERAL (SELECT ST_CollectionExtract(ST_Intersection(ST_MakeValid({pz}), ST_MakeValid({qz})), 3) AS g) i "
            "WHERE p.{cp} IS NOT NULL AND q.{cq} IS NOT NULL AND q.{cat} IS NOT NULL AND NOT ST_IsEmpty(i.g)) "
            "SELECT zone, category, round(sum(ST_Area(g::geography))::numeric, 1) AS area_m2, "
            "round((100 * sum(ST_Area(g::geography)) / NULLIF(max(zone_area), 0))::numeric, 2) AS share_pct, "
            "ST_Multi(ST_Union(g))::geometry(MultiPolygon, 4326) AS geom FROM j GROUP BY pid, zone, category").format(
            zone=sql.Identifier(zone), cat=sql.Identifier(cat), pz=pz, qz=qz, P=sdk.ident(p),
            Q=sdk.ident(q), cp=sql.Identifier(cp), cq=sql.Identifier(cq),
            gq=sdk.in_srid("q", cq, sq, sp))
