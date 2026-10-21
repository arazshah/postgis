"""خروجی ماشین‌خوان پایگاه دانش: ورودی دستیار هوشمند (RAG)، llms.txt و API عمومی.

در خروجی، توکن‌های پلن با مقدار روز جایگزین و پیوندها مطلق می‌شوند تا هر تکه به‌تنهایی قابل فهم و قابل نقل باشد.
"""
from __future__ import annotations

from django.conf import settings

from . import tokens
from .models import Article, ArticleChunk


def _queryset(audience: str):
    qs = Article.objects.filter(status=Article.Status.PUBLISHED, category__is_active=True).select_related("category")
    if audience == "public":
        qs = qs.filter(audience=Article.Audience.PUBLIC)
    elif audience == "member":
        qs = qs.filter(audience__in=[Article.Audience.PUBLIC, Article.Audience.MEMBER])
    return qs


def article_rows(audience: str = "public"):
    base = settings.CANONICAL_URL
    vals = tokens.values()
    for a in _queryset(audience).prefetch_related("related"):
        yield {
            "id": a.slug,
            "url": f"{base}{a.get_absolute_url()}",
            "title": a.title,
            "summary": tokens.resolve(a.summary, vals),
            "kind": a.kind,
            "audience": a.audience,
            "category": {"slug": a.category.slug, "title": a.category.title},
            "keywords": a.keyword_list(),
            "related": [r.slug for r in a.related.all()],
            "reviewed_at": a.reviewed_at.isoformat(),
            "updated_at": a.updated_at.isoformat(),
            "body_markdown": tokens.expand_links(tokens.resolve(a.body, vals), base),
        }


def chunk_rows(audience: str = "public"):
    base = settings.CANONICAL_URL
    vals = tokens.values()
    arts = {a.pk: a for a in _queryset(audience)}
    for c in ArticleChunk.objects.filter(article_id__in=arts).order_by("article_id", "ordinal"):
        a = arts[c.article_id]
        url = f"{base}{a.get_absolute_url()}" + (f"#{c.anchor}" if c.anchor else "")
        text = tokens.expand_links(tokens.resolve(c.text, vals), base)
        yield {
            "id": f"{a.slug}#{c.ordinal}",
            "article": a.slug,
            "url": url,
            "title": a.title,
            "heading": c.heading,
            "category": a.category.title,
            "kind": a.kind,
            "audience": a.audience,
            "updated_at": a.updated_at.isoformat(),
            "hash": c.text_hash,
            "text": text,
            "embedding_text": f"{a.title}\n{c.heading}\n{text}" if c.heading != a.title else f"{a.title}\n{text}",
        }
