from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class Change(ToolPlugin):
    key, order, category, icon = "change", 80, "overlay", "t-change"
    level = "mid"
    title = "تغییر بین دو نسخه"
    description = "دو نسخه‌ی یک لایه چندضلعی (مثلاً کاربری ۱۴۰۰ و ۱۴۰۵) را برش می‌دهد و مساحت هر «از ← به» را می‌دهد."
    inputs, output = ("نسخهٔ قدیم", "نسخهٔ جدید"), "مساحت هر «از ← به»"
    example = "ببین چه مساحتی از کاربری ۱۴۰۰ تا ۱۴۰۵ از زمین کشاورزی به مسکونی تبدیل شد."
    columns = ("from_category", "to_category", "area_m2")
    chart_hint = {"kind": "sankey", "field": "from_category", "target": "to_category", "value": "area_m2", "agg": "sum"}
    params = (
        Param("layer", "layer", "نسخهٔ قدیم", "لایه چندضلعی", geom="polygon"),
        Param("other", "layer", "نسخهٔ جدید", "لایه چندضلعی", geom="polygon"),
        Param("category", "text", "ستون دسته در نسخهٔ قدیم", placeholder="landuse"),
        Param("category2", "text", "ستون دسته در نسخهٔ جدید", placeholder="landuse"),
    )

    def build(self, ctx):
        ex, params = ctx.ex, ctx.params
        p, q = ctx.table("layer"), ctx.table("other")
        cp, sp, _ = sdk.geom_of(p, ("POLYGON",), ex)
        cq, sq, _ = sdk.geom_of(q, ("POLYGON",), ex)
        cat, cat2 = (params.get("category") or "").strip(), (params.get("category2") or "").strip()
        if cat not in ctx.attr_cols(p):
            raise ToolError("ستون دسته‌ی نسخه‌ی قدیم (لایه اول) را انتخاب کنید.")
        if cat2 not in ctx.attr_cols(q):
            raise ToolError("ستون دسته‌ی نسخه‌ی جدید (لایه دوم) را انتخاب کنید.")
        pz, qz = sdk.geom4326("p", cp, sp), sdk.geom4326("q", cq, sq)
        return sql.SQL(
            "WITH j AS (SELECT p.{cat}::text AS from_category, q.{cat2}::text AS to_category, i.g FROM {P} p "
            "JOIN {Q} q ON ST_Intersects(p.{cp}, {gq}) CROSS JOIN LATERAL (SELECT ST_CollectionExtract("
            "ST_Intersection(ST_MakeValid({pz}), ST_MakeValid({qz})), 3) AS g) i WHERE p.{cp} IS NOT NULL AND q.{cq} IS NOT NULL "
            "AND p.{cat} IS NOT NULL AND q.{cat2} IS NOT NULL AND NOT ST_IsEmpty(i.g)) "
            "SELECT from_category, to_category, round(sum(ST_Area(g::geography))::numeric, 1) AS area_m2, "
            "ST_Multi(ST_Union(g))::geometry(MultiPolygon, 4326) AS geom FROM j GROUP BY 1, 2").format(
            cat=sql.Identifier(cat), cat2=sql.Identifier(cat2), P=sdk.ident(p),
            Q=sdk.ident(q), cp=sql.Identifier(cp), cq=sql.Identifier(cq), pz=pz, qz=qz,
            gq=sdk.in_srid("q", cq, sq, sp))
