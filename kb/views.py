import json

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.db.models import Count, Q
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.safestring import mark_safe
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_POST

from . import export, tokens
from . import render as renderer
from . import search as searching
from . import text as fa
from .models import Article, Category, Feedback

PAGE_SIZE = 20
CACHE_PUBLIC = cache_control(public=True, max_age=600)


def _jsonld(data) -> str:
    """JSON-LD امن برای قرار گرفتن داخل <script>."""
    return mark_safe(json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))  # noqa: S308


def _categories(user):
    visible_q = Q(articles__status=Article.Status.PUBLISHED)
    levels = [Article.Audience.PUBLIC]
    if user.is_authenticated:
        levels.append(Article.Audience.MEMBER)
        if user.is_staff:
            levels.append(Article.Audience.STAFF)
    visible_q &= Q(articles__audience__in=levels)
    cats = Category.objects.filter(is_active=True).annotate(n=Count("articles", filter=visible_q))
    return [c for c in cats if c.n]


def index(request):
    base = searching.visible(request.user)
    ctx = {
        "categories": _categories(request.user),
        "featured": list(base.filter(is_featured=True)[:8]),
        "recent": list(base.order_by("-updated_at")[:6]),
        "total": base.count(),
        "jsonld": _jsonld({
            "@context": "https://schema.org", "@type": "WebSite",
            "name": f"پایگاه دانش {tokens.values()['site_name']}", "url": f"{settings.CANONICAL_URL}/kb/",
            "inLanguage": "fa-IR",
            "potentialAction": {"@type": "SearchAction", "target": f"{settings.CANONICAL_URL}/kb/search/?q={{q}}",
                                "query-input": "required name=q"}}),
    }
    return render(request, "kb/index.html", ctx)


def search(request):
    q = (request.GET.get("q") or "").strip()[:200]
    cat = request.GET.get("c") or None
    results = searching.search(q, request.user, limit=60, category=cat) if q else []
    if q and not results:
        searching.log_missed(q)
    ctx = {"q": q, "results": results, "categories": _categories(request.user), "cat": cat,
           "suggest": list(searching.visible(request.user).filter(is_featured=True)[:6]) if q and not results else []}
    return render(request, "kb/search.html", ctx)


def category(request, slug):
    cat = get_object_or_404(Category, slug=slug, is_active=True)
    arts = list(searching.visible(request.user).filter(category=cat))
    if not arts:
        raise Http404
    return render(request, "kb/category.html", {"cat": cat, "articles": arts, "categories": _categories(request.user)})


def _article_jsonld(art, summary_text, url):
    base = settings.CANONICAL_URL
    graph = [
        {"@type": "BreadcrumbList", "itemListElement": [
            {"@type": "ListItem", "position": 1, "name": "پایگاه دانش", "item": f"{base}/kb/"},
            {"@type": "ListItem", "position": 2, "name": art.category.title, "item": f"{base}{art.category.get_absolute_url()}"},
            {"@type": "ListItem", "position": 3, "name": art.title, "item": url}]},
    ]
    if art.kind == Article.Kind.FAQ:
        graph.append({"@type": "FAQPage", "mainEntity": [{
            "@type": "Question", "name": art.title,
            "acceptedAnswer": {"@type": "Answer", "text": summary_text}}]})
    else:
        graph.append({"@type": "TechArticle", "headline": art.title, "description": summary_text, "inLanguage": "fa-IR",
                      "dateModified": art.updated_at.date().isoformat(), "mainEntityOfPage": url,
                      "author": {"@type": "Organization", "name": "ژئوپایگاه", "url": f"{base}/"}})
    return _jsonld({"@context": "https://schema.org", "@graph": graph})


def article(request, slug):
    art = get_object_or_404(Article.objects.select_related("category"), slug=slug)
    staff = request.user.is_authenticated and request.user.is_staff
    if not art.is_visible and not staff:
        raise Http404
    if art.audience == Article.Audience.STAFF and not staff:
        raise Http404
    if art.audience == Article.Audience.MEMBER and not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())

    vals = tokens.values()
    html, heads = renderer.article_html(art, vals)
    summary = renderer.resolved_summary(art, vals)
    peers = list(searching.visible(request.user).filter(category=art.category))
    idx = next((i for i, a in enumerate(peers) if a.pk == art.pk), None)
    allowed = set(searching.visible(request.user).values_list("pk", flat=True))
    related = [r for r in art.related.select_related("category") if r.pk in allowed]
    if len(related) < 3:  # تکمیل با هم‌دسته‌ای‌ها
        for p in peers:
            if p.pk != art.pk and p not in related and len(related) < 4:
                related.append(p)
    url = settings.CANONICAL_URL + art.get_absolute_url()
    ctx = {
        "a": art, "body_html": html, "summary": summary, "toc": [h for h in heads if h[0] == 2] if len(heads) >= 3 else [],
        "related": related, "prev": peers[idx - 1] if idx else None,
        "next": peers[idx + 1] if idx is not None and idx + 1 < len(peers) else None,
        "jsonld": _article_jsonld(art, fa.plain_text(summary), url),
        "voted": art.pk in request.session.get("kb_voted", []),
        "noindex": art.audience != Article.Audience.PUBLIC or art.status != Article.Status.PUBLISHED,
    }
    return render(request, "kb/article.html", ctx)


@require_POST
def feedback(request, slug):
    art = get_object_or_404(Article, slug=slug, status=Article.Status.PUBLISHED)
    if art.audience == Article.Audience.STAFF and not (request.user.is_authenticated and request.user.is_staff):
        raise Http404
    voted = request.session.get("kb_voted", [])
    if art.pk in voted:
        messages.info(request, "بازخورد شما قبلاً ثبت شده است.")
    else:
        helpful = request.POST.get("helpful") == "1"
        if not request.session.session_key:
            request.session.save()
        Feedback.objects.create(article=art, helpful=helpful, comment=(request.POST.get("comment") or "").strip()[:500],
                                session_key=(request.session.session_key or "")[:40])
        request.session["kb_voted"] = voted[-200:] + [art.pk]
        messages.success(request, "ممنون از بازخوردتان." if helpful else "ممنون؛ تلاش می‌کنیم این مقاله را بهتر کنیم.")
    return redirect(art)


# ---------------- خروجی ماشین‌خوان ----------------

@CACHE_PUBLIC
def api_articles(request):
    full = request.GET.get("full") == "1"
    rows = list(export.article_rows("public"))
    if not full:
        for r in rows:
            r.pop("body_markdown", None)
    return JsonResponse({"count": len(rows), "articles": rows}, json_dumps_params={"ensure_ascii": False})


@CACHE_PUBLIC
def api_chunks(request):
    body = "\n".join(json.dumps(r, ensure_ascii=False) for r in export.chunk_rows("public")) + "\n"
    return HttpResponse(body, content_type="application/x-ndjson; charset=utf-8")


@CACHE_PUBLIC
def llms_txt(request):
    """فهرست مقاله‌ها برای مدل‌های زبانی و خزنده‌ها (قالب llms.txt)."""
    base = settings.CANONICAL_URL
    vals = tokens.values()
    arts = list(searching.public_only())
    lines = [f"# {vals['site_name']} (postgis.ir)", "",
             "> پایگاه داده مکانی PostGIS به‌صورت سرویس برای WebGIS، QGIS و GeoServer؛ ساخت با شماره موبایل و "
             "اطلاعات اتصال آماده. این فهرست مقاله‌های پایگاه دانش است.", "",
             f"متن کامل همه مقاله‌ها: {base}/llms-full.txt", ""]
    by_cat: dict = {}
    for a in arts:
        by_cat.setdefault(a.category, []).append(a)
    for cat, items in by_cat.items():
        lines += [f"## {cat.title}", ""]
        lines += [f"- [{a.title}]({base}{a.get_absolute_url()}): {fa.plain_text(tokens.resolve(a.summary, vals))}"
                  for a in items]
        lines.append("")
    return HttpResponse("\n".join(lines), content_type="text/plain; charset=utf-8")


@CACHE_PUBLIC
def llms_full_txt(request):
    out = [f"# پایگاه دانش {tokens.values()['site_name']}", ""]
    for r in export.article_rows("public"):
        out += [f"# {r['title']}", f"آدرس: {r['url']}", f"دسته: {r['category']['title']}", "",
                f"**پاسخ کوتاه:** {r['summary']}", "", r["body_markdown"], "", "---", ""]
    return HttpResponse("\n".join(out), content_type="text/plain; charset=utf-8")
