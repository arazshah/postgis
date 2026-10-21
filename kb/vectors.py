"""جست‌وجوی معنایی با pgvector برای دستیار هوشمند.

ستون‌های embedding عمداً در مدل Django تعریف نمی‌شوند و با SQL مستقیم مدیریت می‌شوند؛ به این ترتیب:
- روی پایگاه داده‌ای که افزونه vector ندارد (توسعه با SQLite یا Postgres ساده) مایگریشن خطا نمی‌دهد و
  دستیار با جست‌وجوی کلیدواژه‌ای کار می‌کند؛
- ستون بدون بُعد ثابت است و با عوض شدن مدل embedding نیازی به مایگریشن نیست (چند صد تکه، جست‌وجوی دقیق).
"""
from __future__ import annotations

import logging

from django.db import DatabaseError, connection, transaction

log = logging.getLogger(__name__)

TABLE = "kb_articlechunk"
_ready_cache: dict[str, bool] = {}


def _pg() -> bool:
    return connection.vendor == "postgresql"


def setup(conn=None) -> bool:
    """افزونه و ستون‌ها را (اگر ممکن باشد) می‌سازد؛ ایمن و تکرارپذیر. True یعنی آماده است."""
    conn = conn or connection
    if conn.vendor != "postgresql":
        return False
    if conn is connection and available():
        return True  # ستون‌ها از قبل هست؛ ALTER تکراری لازم نیست (و وسط تراکنش باز ممکن است قفل بگیرد)
    try:
        with transaction.atomic(using=conn.alias), conn.cursor() as cur:
            cur.execute("SELECT 1 FROM pg_available_extensions WHERE name = 'vector'")
            if not cur.fetchone():
                return False
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS embedding vector")
            cur.execute(f"ALTER TABLE {TABLE} ADD COLUMN IF NOT EXISTS embedding_model varchar(100) NOT NULL DEFAULT ''")
    except DatabaseError as exc:
        log.warning("pgvector آماده نشد: %s", exc)
        return False
    _ready_cache.pop(conn.alias, None)
    return True


def available() -> bool:
    """آیا ستون embedding روی این پایگاه داده هست؟ (نتیجه مثبت کش می‌شود)"""
    if not _pg():
        return False
    if _ready_cache.get(connection.alias):
        return True
    with connection.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = 'embedding'", [TABLE])
        ok = cur.fetchone() is not None
    if ok:
        _ready_cache[connection.alias] = True
    return ok


def literal(vec: list[float]) -> str:
    return "[" + ",".join(f"{float(x):.7g}" for x in vec) + "]"


def store(chunk_id: int, vec: list[float], model: str) -> None:
    with connection.cursor() as cur:
        cur.execute(f"UPDATE {TABLE} SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
                    [literal(vec), model[:100], chunk_id])


def pending(model: str, *, force: bool = False) -> list[int]:
    """شناسه تکه‌های منتشرشده‌ای که برای این مدل embedding ندارند."""
    if not available():
        return []
    cond = "TRUE" if force else "(c.embedding IS NULL OR c.embedding_model <> %s)"
    params = [] if force else [model]
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT c.id FROM {TABLE} c JOIN kb_article a ON a.id = c.article_id "
            f"WHERE a.status = 'published' AND {cond} ORDER BY c.id", params)
        return [r[0] for r in cur.fetchall()]


def stats(model: str) -> tuple[int, int]:
    """(کل تکه‌های منتشرشده، تکه‌های دارای embedding برای این مدل)"""
    with connection.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {TABLE} c JOIN kb_article a ON a.id = c.article_id "
                    "WHERE a.status = 'published'")
        total = cur.fetchone()[0]
        if not available():
            return total, 0
        cur.execute(
            f"SELECT count(*) FROM {TABLE} c JOIN kb_article a ON a.id = c.article_id "
            "WHERE a.status = 'published' AND c.embedding IS NOT NULL AND c.embedding_model = %s", [model])
        return total, cur.fetchone()[0]


def nearest(vec: list[float], model: str, article_ids: list[int], limit: int = 8) -> list[tuple[int, float]]:
    """نزدیک‌ترین تکه‌ها (فاصله کسینوسی) فقط میان مقاله‌های مجاز؛ [(chunk_id, distance)]."""
    if not article_ids or not available():
        return []
    q = literal(vec)
    with connection.cursor() as cur:
        cur.execute(
            f"SELECT id, embedding <=> %s::vector AS d FROM {TABLE} "
            "WHERE embedding IS NOT NULL AND embedding_model = %s AND vector_dims(embedding) = %s "
            "AND article_id = ANY(%s) ORDER BY d LIMIT %s",
            [q, model, len(vec), list(article_ids), limit])
        return [(r[0], float(r[1])) for r in cur.fetchall()]
