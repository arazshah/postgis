"""ساخت embedding برای تکه‌های پایگاه دانش (فقط تکه‌های بدون embedding یا با مدل قدیمی)."""
from __future__ import annotations

import logging

from . import tokens, vectors
from .models import ArticleChunk

log = logging.getLogger(__name__)
BATCH = 48


def chunk_text(chunk: ArticleChunk, vals: dict[str, str]) -> str:
    text = tokens.resolve(chunk.text, vals)
    title = chunk.article.title
    return (f"{title}\n{text}" if chunk.heading == title else f"{title}\n{chunk.heading}\n{text}")[:6000]


def embed_pending(conf=None, *, force: bool = False, limit: int | None = None) -> dict:
    """{'embedded': n, 'remaining': n, 'error': str}. با نبود کلید یا افزونه، بدون خطا برمی‌گردد."""
    from assistant import llm
    from core.models import SiteSettings

    conf = conf or SiteSettings.get()
    out = {"embedded": 0, "remaining": 0, "error": ""}
    if not conf.assistant_key_ready:
        out["error"] = "کلید API وارد نشده است."
        return out
    if not vectors.available() and not vectors.setup():
        out["error"] = "افزونه pgvector روی پایگاه داده پنل نصب نیست."
        return out
    model = conf.assistant_embedding_model
    ids = vectors.pending(model, force=force)
    out["remaining"] = len(ids)
    if limit:
        ids = ids[:limit]
    vals = tokens.values()
    for i in range(0, len(ids), BATCH):
        part = ids[i:i + BATCH]
        chunks = {c.pk: c for c in ArticleChunk.objects.filter(pk__in=part).select_related("article")}
        ordered = [chunks[p] for p in part if p in chunks]
        try:
            vecs = llm.embed(conf, [chunk_text(c, vals) for c in ordered])
        except llm.LLMError as exc:
            out["error"] = str(exc)
            break
        for c, v in zip(ordered, vecs, strict=True):
            vectors.store(c.pk, v, model)
        out["embedded"] += len(ordered)
        out["remaining"] -= len(ordered)
    return out


