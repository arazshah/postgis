from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class Knn(ToolPlugin):
    key, order, category, icon = "knn", 40, "proximity", "t-knn"
    level = "mid"
    title = "k نزدیک‌ترین همسایه"
    description = "برای هر عارضه، k نزدیک‌ترین عارضه‌ی لایه‌ی دیگر را با خط اتصال، رتبه و فاصله می‌دهد."
    inputs, output = ("لایه مبدأ", "لایه هدف"), "خط‌های اتصال + رتبه و فاصله"
    example = "برای هر مدرسه، سه درمانگاه نزدیک و فاصله‌ی هر کدام."
    columns = ("ستون‌های لایه مبدأ", "rank", "distance_m", "nearest_name (اختیاری)", "geom")
    chart_hint = {"kind": "hist", "field": "distance_m"}
    params = (
        Param("layer", "layer", "لایه مبدأ"),
        Param("other", "layer", "لایه هدف", "همسایه‌ها از این لایه پیدا می‌شوند"),
        Param("k", "number", "تعداد همسایه (k)", "بین ۱ تا ۲۰", "3", unit="همسایه"),
        Param("label", "text", "ستون نام در لایه هدف", "اختیاری", required=False, placeholder="name", group="advanced"),
    )

    def build(self, ctx):
        a, b = ctx.table("layer"), ctx.table("other")
        ca, sa, _ = sdk.geom_of(a)
        cb, sb, _ = sdk.geom_of(b)
        k = int(ctx.number("k", 1, 20))
        label = ctx.column("label", b)
        ctx.guard(a, ca, 50_000, "این ابزار تا ۵۰٬۰۰۰ عارضه‌ی مبدأ را پشتیبانی می‌کند.")
        ga = sdk.geom4326("a", ca, sa)
        ga_in_b = sql.SQL("ST_Transform({}, {})").format(ga, sql.Literal(sb)) if sb not in (0, 4326) else ga
        lbl_in = sql.SQL("b.{} AS lbl, ").format(sql.Identifier(label)) if label else sql.SQL("")
        return sql.SQL(
            "SELECT {attrs}n.rnk::int AS rank, round(ST_Distance({ga}::geography, n.bg::geography)::numeric, 1) AS distance_m{lbl_out}, "
            "ST_MakeLine(ST_PointOnSurface({ga}::geometry), ST_PointOnSurface(n.bg)) AS geom "
            "FROM {A} a CROSS JOIN LATERAL (SELECT {gb} AS bg, {lbl_in}row_number() OVER (ORDER BY b.{cb} <-> {gab}) AS rnk "
            "FROM {B} b WHERE b.{cb} IS NOT NULL ORDER BY b.{cb} <-> {gab} LIMIT {k}) n WHERE a.{ca} IS NOT NULL").format(
            attrs=sdk.attr_sql(ctx.ex, a, "a"), ga=ga, A=sdk.ident(a), B=sdk.ident(b), gb=sdk.geom4326("b", cb, sb),
            lbl_in=lbl_in, lbl_out=sql.SQL(", n.lbl AS nearest_name") if label else sql.SQL(""),
            cb=sql.Identifier(cb), gab=ga_in_b, k=sql.Literal(k), ca=sql.Identifier(ca))

    def summary_extra(self, params):
        return [f"k = {params['k']}"] if params.get("k") else []
