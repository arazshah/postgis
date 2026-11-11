"""بخش مشترک «برش با مرز» و «حذف ناحیه»: ماسک یکپارچه‌ی لایه‌ی دوم."""
from psycopg import sql

from tools import sdk


def mask_sql(q, cq, sq):
    return sql.SQL("WITH m AS (SELECT ST_Union(ST_MakeValid({g})) AS g FROM {Q} q WHERE q.{c} IS NOT NULL) ").format(
        g=sdk.geom4326("q", cq, sq), Q=sdk.ident(q), c=sql.Identifier(cq))
