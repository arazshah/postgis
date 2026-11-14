"""بخش مشترک «برش با مرز» و «حذف ناحیه»: ماسک یکپارچه‌ی لایه‌ی دوم."""
from psycopg import sql

from tools import sdk


def mask_sql(q, cq, sq):
    return sql.SQL("WITH m AS (SELECT ST_Union(ST_MakeValid({g})) AS g FROM {Q} q WHERE q.{c} IS NOT NULL) ").format(
        g=sdk.geom4326("q", cq, sq), Q=sdk.ident(q), c=sql.Identifier(cq))


def side_cols(ex, t, alias: str, prefix: str, *, null: bool):
    """ستون‌های صفاتی یک لایه با پیشوند؛ `null=True` همان ستون‌ها را تهی می‌دهد (برای شاخه‌های UNION)."""
    out = []
    for c in ex.columns(t):
        if c["spatial"] or c["name"] == "gid":
            continue
        name = sql.Identifier(f"{prefix}{c['name']}"[:63])
        out.append(sql.SQL("NULL AS {}").format(name) if null else
                   sql.SQL("{}.{} AS {}").format(sql.Identifier(alias), sql.Identifier(c["name"]), name))
    return out


def pieces(ctx, parts: tuple[str, ...]):
    """اجتماع/تفاضل متقارن دو لایه‌ی چندضلعی: بخش‌های «هر دو» (both)، «فقط اول» (a) و «فقط دوم» (b) با ستون part."""
    ex = ctx.ex
    a, b = ctx.table("layer"), ctx.table("other")
    ca, sa, _ = sdk.geom_of(a, ("POLYGON",), ex)
    cb, sb, _ = sdk.geom_of(b, ("POLYGON",), ex)
    ctx.guard(a, ca, 20_000, "لایه‌ی اول تا ۲۰٬۰۰۰ چندضلعی مجاز است.")
    ctx.guard(b, cb, 20_000, "لایه‌ی دوم تا ۲۰٬۰۰۰ چندضلعی مجاز است.")
    ga, gb = sdk.geom4326("a", ca, sa), sdk.geom4326("b", cb, sb)
    ident = sql.Identifier
    empty = sql.SQL("ST_GeomFromText('POLYGON EMPTY', 4326)")

    def cols(an, bn):  # با ویرگول پایانی (یا خالی)
        parts_ = side_cols(ex, a, "a", "a_", null=not an) + side_cols(ex, b, "b", "b_", null=not bn)
        return sql.SQL(", ").join(parts_) + sql.SQL(", ") if parts_ else sql.SQL("")

    branches = []
    if "both" in parts:
        branches.append(sql.SQL(
            "SELECT {cols}'both' AS part, ST_CollectionExtract(ST_Intersection(ST_MakeValid({ga}), ST_MakeValid({gb})), 3) AS geom "
            "FROM {A} a JOIN {B} b ON ST_Intersects(b.{cb}, {ain}) WHERE a.{ca} IS NOT NULL").format(
            cols=cols(True, True),
            ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b), cb=ident(cb), ca=ident(ca), ain=sdk.in_srid("a", ca, sa, sb)))
    if "a" in parts:
        branches.append(sql.SQL(
            "SELECT {cols}'a_only' AS part, ST_CollectionExtract(ST_Difference(ST_MakeValid({ga}), coalesce(m.g, {empty})), 3) AS geom "
            "FROM {A} a CROSS JOIN LATERAL (SELECT ST_Union(ST_MakeValid({gb})) AS g FROM {B} b "
            "WHERE b.{cb} IS NOT NULL AND ST_Intersects(b.{cb}, {ain})) m WHERE a.{ca} IS NOT NULL").format(
            cols=cols(True, False),
            ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b), cb=ident(cb), ca=ident(ca), empty=empty,
            ain=sdk.in_srid("a", ca, sa, sb)))
    if "b" in parts:
        bin_ = sdk.in_srid("b", cb, sb, sa)
        branches.append(sql.SQL(
            "SELECT {cols}'b_only' AS part, ST_CollectionExtract(ST_Difference(ST_MakeValid({gb}), coalesce(m.g, {empty})), 3) AS geom "
            "FROM {B} b CROSS JOIN LATERAL (SELECT ST_Union(ST_MakeValid({ga})) AS g FROM {A} a "
            "WHERE a.{ca} IS NOT NULL AND ST_Intersects(a.{ca}, {bin})) m WHERE b.{cb} IS NOT NULL").format(
            cols=cols(False, True),
            ga=ga, gb=gb, A=sdk.ident(a), B=sdk.ident(b), cb=ident(cb), ca=ident(ca), empty=empty, bin=bin_))
    return sql.SQL("SELECT * FROM (") + sql.SQL(" UNION ALL ").join(branches) + sql.SQL(") u WHERE u.geom IS NOT NULL AND NOT ST_IsEmpty(u.geom)")
