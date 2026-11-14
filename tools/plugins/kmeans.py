from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin


@sdk.register
class KMeans(ToolPlugin):
    key, order, category, icon = "kmeans", 40, "stats", "t-kmeans"
    level = "mid"
    title = "خوشه‌بندی K-Means"
    description = "عارضه‌ها را به تعداد دلخواه گروه (k) هم‌اندازه‌ی مکانی تقسیم می‌کند؛ برای ساخت منطقه‌ی کاری یا حوزه‌ی سرویس."
    inputs, output = ("هر لایه",), "همان عارضه‌ها + شماره‌ی خوشه و اندازه‌اش"
    example = "تقسیم ۲٬۰۰۰ مشترک به ۸ مسیر برای اکیپ‌های قرائت کنتور."
    columns = ("ستون‌های لایه ورودی", "cluster_id", "cluster_size", "geom")
    chart_hint = {"kind": "hist", "field": "cluster_size"}
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("k", "number", "تعداد خوشه‌ها (k)", "", "5", unit="خوشه"),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        k = int(ctx.number("k", 2, 200))
        ctx.guard(t, col, 100_000, "این ابزار تا ۱۰۰٬۰۰۰ عارضه را پشتیبانی می‌کند.")
        g = sdk.geom4326("s", col, srid)
        return sql.SQL(
            "SELECT {attrs}k.cid + 1 AS cluster_id, count(*) OVER (PARTITION BY k.cid) AS cluster_size, k._g AS geom FROM "
            "(SELECT s.*, {g}::geometry AS _g, ST_ClusterKMeans(ST_Transform(ST_PointOnSurface({g}), 3857), "
            "least({k}, greatest((SELECT count(*) FROM {src} WHERE {c} IS NOT NULL), 1))::int) OVER () AS cid "
            "FROM {src} s WHERE s.{c} IS NOT NULL) k").format(
            attrs=sdk.attr_sql(ctx.ex, t, "k"), g=g, k=sql.Literal(k), src=sdk.ident(t), c=sql.Identifier(col))

    def summary_extra(self, params):
        return [f"k = {params['k']}"] if params.get("k") else []
