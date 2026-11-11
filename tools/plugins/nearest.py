from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolError, ToolPlugin


@sdk.register
class Nearest(ToolPlugin):
    key, order, category, icon = "nearest", 20, "proximity", "t-nearest"
    title = "نزدیک‌ترین عارضه"
    description = "برای هر عارضه، نزدیک‌ترین عارضه لایه دیگر و فاصله‌اش به متر."
    inputs, output = ("لایه مبدأ", "لایه هدف"), "همان عارضه‌ها + فاصله"
    example = "برای هر مدرسه نزدیک‌ترین پارک و فاصلهٔ آن را پیدا کن."
    columns = ("ستون‌های لایه مبدأ", "distance_m", "nearest_name (اختیاری)")
    chart_hint = {"kind": "hist", "field": "distance_m", "cumulative": "1"}
    params = (
        Param("layer", "layer", "لایه مبدأ"),
        Param("other", "layer", "لایه هدف", "نزدیک‌ترینِ این لایه پیدا می‌شود"),
        Param("label", "text", "ستون نام در لایه هدف", "اختیاری؛ برای نوشتن نام نزدیک‌ترین", required=False, placeholder="name"),
    )

    def build(self, ctx):
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a)
        cb, sb, _ = sdk.geom_of(b)
        label = ctx.params.get("label") or ""
        if label and label not in ctx.cols(b):
            raise ToolError("ستون نام لایه دوم نامعتبر است.")
        ga = sdk.geom4326("a", ca, sa)
        # نمایه مکانی لایه دوم: مرتب‌سازی <-> در SRID خود آن
        ga_in_b = sql.SQL("ST_Transform({}, {})").format(ga, sql.Literal(sb)) if sb not in (0, 4326) else ga
        gb_raw = sql.SQL("n.{}").format(sql.Identifier(cb))
        gb = sdk.geom4326("n", cb, sb)
        return sql.SQL(
            "SELECT {attrs}{lbl} round(ST_Distance({ga}::geography, {gb}::geography)::numeric, 1) AS distance_m, "
            "{ga}::geometry AS geom FROM {A} a CROSS JOIN LATERAL (SELECT * FROM {B} n WHERE n.{cb} IS NOT NULL "
            "ORDER BY {gbr} <-> {gab} LIMIT 1) n WHERE a.{ca} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, a, "a"),
            lbl=sql.SQL("n.{} AS nearest_name,").format(sql.Identifier(label)) if label else sql.SQL(""),
            ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b),
            cb=sql.Identifier(cb), gbr=gb_raw, gab=ga_in_b, ca=sql.Identifier(ca))
