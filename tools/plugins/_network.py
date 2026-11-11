"""بخش مشترک ابزارهای شبکه که از لایه‌ی نقطه‌ای شروع می‌کنند: نزدیک‌ترین رأس شبکه به هر نقطه."""
from psycopg import sql

from tools import sdk


def vertex_join(ca, sa):
    return sql.SQL("CROSS JOIN LATERAL (SELECT id FROM routing.ways_vertices_pgr ORDER BY the_geom <-> {g} LIMIT 1) v").format(
        g=sdk.geom4326("a", ca, sa))
