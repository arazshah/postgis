from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

CAP = 5000


@sdk.register
class Voronoi(ToolPlugin):
    key, order, category, icon = "voronoi", 70, "proximity", "t-voronoi"
    level = "mid"
    title = "حوزه نفوذ (تیسن)"
    description = "هر نقطه از محدوده را به نزدیک‌ترین مرکز نسبت می‌دهد؛ برای حوزه‌ی خدمات کلانتری‌ها یا شعبه‌ها."
    inputs, output = ("لایه نقطه‌ای", "مرز (اختیاری)"), "حوزه نفوذ هر نقطه"
    example = "حوزه‌ی خدمات هر کلانتری: هر نقطه‌ی شهر به نزدیک‌ترین کلانتری می‌رسد."
    columns = ("ستون‌های لایه نقطه‌ای", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه مراکز", "مثلاً کلانتری‌ها", geom="point"),
        Param("other", "layer", "مرز برش (اختیاری)", "بدون مرز، حوزه‌های بیرونی تا مرز تقریبی داده‌ها کشیده می‌شوند",
              required=False, geom="polygon", empty="بدون مرز"),
    )

    def build(self, ctx):
        ident, ex = sql.Identifier, ctx.ex
        p = ctx.table("layer")
        cp, sp, _ = sdk.geom_of(p, ("POINT",), ex)
        ctx.guard(p, cp, CAP, f"حوزه نفوذ تا {CAP} نقطه را پشتیبانی می‌کند؛ لایه را کوچک‌تر کنید.")
        clip_t = ctx.table("other") if ctx.params.get("other") else None
        mask, cell = sql.SQL(""), sql.SQL("cells.cell")
        if clip_t is not None:
            cq, sq, _ = sdk.geom_of(clip_t, ("POLYGON",), ex)
            mask = sql.SQL(", mask AS (SELECT ST_Union(ST_MakeValid({g})) AS g FROM {Q} q WHERE q.{c} IS NOT NULL)").format(
                g=sdk.geom4326("q", cq, sq), Q=sdk.ident(clip_t), c=ident(cq))
            cell = sql.SQL("ST_CollectionExtract(ST_Intersection(ST_MakeValid(cells.cell), mask.g), 3)")
        return sql.SQL(
            "WITH pts AS (SELECT {attrs}{g}::geometry AS g FROM {P} p WHERE p.{cp} IS NOT NULL), "
            "cells AS (SELECT (ST_Dump(ST_VoronoiPolygons((SELECT ST_Collect(g) FROM pts)))).geom AS cell){mask} "
            "SELECT {out_attrs}round(ST_Area(r.g::geography)::numeric, 1) AS area_m2, r.g AS geom FROM cells "
            "JOIN pts ON ST_Contains(cells.cell, pts.g) {mask_join}CROSS JOIN LATERAL (SELECT {cell} AS g) r "
            "WHERE NOT ST_IsEmpty(r.g)").format(
            attrs=sdk.attr_sql(ex, p, "p"), g=sdk.geom4326("p", cp, sp), P=sdk.ident(p), cp=ident(cp), mask=mask,
            out_attrs=sdk.attr_sql(ex, p, "pts"), cell=cell,
            mask_join=sql.SQL("CROSS JOIN mask ") if clip_t is not None else sql.SQL(""))
