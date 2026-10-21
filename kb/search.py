"""جست‌وجوی فارسی در پایگاه دانش.

مجموعه مقاله‌ها کوچک است (صدها مقاله)، پس رتبه‌بندی در پایتون و مستقل از نوع پایگاه داده انجام می‌شود؛ بدون
افزونه و بدون وابستگی به PostgreSQL. جست‌وجوی معنایی (pgvector) برای دستیار جداگانه روی تکه‌ها ساخته می‌شود.
"""
from __future__ import annotations

from django.db.models import F, Q

from . import text as fa
from .models import Article, MissedQuery

W_TITLE, W_KEYWORDS, W_SUMMARY, W_BODY = 6, 5, 3, 1
MAX_MISSED_ROWS = 5000


def visible(user=None):
    """مقاله‌های قابل دیدن برای این کاربر (مخاطب و وضعیت)."""
    levels = [Article.Audience.PUBLIC]
    if user is not None and getattr(user, "is_authenticated", False):
        levels.append(Article.Audience.MEMBER)
        if getattr(user, "is_staff", False):
            levels.append(Article.Audience.STAFF)
    return (Article.objects.filter(status=Article.Status.PUBLISHED, category__is_active=True, audience__in=levels)
            .select_related("category"))


def public_only():
    return visible(None)


def _score(article: Article, toks: list[str], phrase: str) -> int:
    title = fa.normalize(article.title)
    kws = fa.normalize(article.keywords)
    summ = fa.normalize(article.summary)
    body = article.search_text
    score = 0
    for t in toks:
        if t in title:
            score += W_TITLE + (2 if f" {t}" in f" {title}" else 0)
        if t in kws:
            score += W_KEYWORDS
        if t in summ:
            score += W_SUMMARY
        if t in body:
            score += W_BODY
    if phrase and len(toks) > 1:
        if phrase in title:
            score += 10
        elif phrase in body:
            score += 4
    if article.is_featured:
        score += 1
    return score


def search(query: str, user=None, *, limit: int = 20, category: str | None = None) -> list[tuple[Article, int]]:
    toks = list(dict.fromkeys(fa.tokens(query)))[:8]
    if not toks:
        return []
    phrase = " ".join(fa.normalize(query).split())
    qs = visible(user)
    if category:
        qs = qs.filter(category__slug=category)

    def run(match_all: bool):
        cond = Q()
        for t in toks:
            q = Q(search_text__contains=t)
            cond = (cond & q) if match_all else (cond | q)
        return list(qs.filter(cond))

    found = run(True)
    if len(found) < 3 and len(toks) > 1:  # گسترش به «هر کدام از واژه‌ها» با رتبه پایین‌تر
        extra = [a for a in run(False) if a.pk not in {x.pk for x in found}]
        found += extra
    ranked = sorted(((a, _score(a, toks, phrase)) for a in found), key=lambda x: (-x[1], x[0].order, x[0].id))
    return ranked[:limit]


def log_missed(query: str) -> None:
    """ثبت جست‌وجوی بی‌نتیجه؛ فقط شمارنده نگه داشته می‌شود و هیچ نشانی از کاربر نیست."""
    norm = " ".join(fa.normalize(query).split())[:200]
    if len(norm) < 3:
        return
    row = MissedQuery.objects.filter(query_norm=norm).first()
    if row:
        MissedQuery.objects.filter(pk=row.pk).update(count=F("count") + 1, resolved=False)
    elif MissedQuery.objects.count() < MAX_MISSED_ROWS:
        MissedQuery.objects.create(query_norm=norm, sample=query.strip()[:200])
