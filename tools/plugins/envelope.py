from psycopg import sql

from tools import sdk
from tools.sdk import Param, ToolPlugin

from ._common import unary


@sdk.register
class Envelope(ToolPlugin):
    key, order, category, icon = "envelope", 30, "geometry", "t-envelope"
    level = "mid"
    title = "کادر محیطی"
    description = "کادر دور عارضه‌ها: مستطیل موازی محورها، مستطیل چرخیده‌ی کم‌مساحت یا کوچک‌ترین دایره."
    inputs, output = ("هر لایه",), "مستطیل یا دایره‌ی محیطی"
    example = "کادر پوشش هر پروژه برای ساخت شاخص نقشه یا محدوده‌ی برداشت."
    columns = ("ستون‌های لایه ورودی (حالت «هر عارضه»)", "area_m2", "geom")
    params = (
        Param("layer", "layer", "لایه ورودی"),
        Param("shape", "choice", "شکل کادر", default="bbox", required=False,
              choices=(("bbox", "مستطیل"), ("rotated", "مستطیل چرخیده"), ("circle", "کوچک‌ترین دایره"))),
        Param("scope", "choice", "محدوده", default="each", required=False,
              choices=(("each", "برای هر عارضه"), ("all", "برای کل لایه"))),
    )

    def build(self, ctx):
        t = ctx.table("layer")
        col, srid, _ = sdk.geom_of(t)
        fn = {"bbox": "ST_Envelope", "rotated": "ST_OrientedEnvelope", "circle": "ST_MinimumBoundingCircle"}[
            ctx.choice("shape", ("bbox", "rotated", "circle"), "bbox")]
        g = sdk.geom4326("s", col, srid)
        if ctx.choice("scope", ("each", "all"), "each") == "all":
            return sql.SQL("SELECT h.n AS feature_count, round(ST_Area(h.g::geography)::numeric, 1) AS area_m2, h.g AS geom FROM "
                           "(SELECT count(*) AS n, {fn}(ST_Collect({g})) AS g FROM {src} s WHERE s.{c} IS NOT NULL) h "
                           "WHERE GeometryType(h.g) = 'POLYGON'").format(fn=sql.SQL(fn), g=g, src=sdk.ident(t), c=sql.Identifier(col))
        e = sql.SQL("{fn}({g})").format(fn=sql.SQL(fn), g=g)
        return unary(ctx, t, col, e, extra=sql.SQL("round(ST_Area({e}::geography)::numeric, 1) AS area_m2, ").format(e=e),
                     where=sql.SQL("GeometryType({e}) = 'POLYGON'").format(e=e))
