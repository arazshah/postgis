from . import text as fa
from . import tokens


def article_html(article, vals=None):
    """(html امن، سرفصل‌ها) برای نمایش مقاله."""
    body = tokens.expand_links(tokens.resolve(article.body, vals))
    return fa.render_markdown(body)


def article_markdown(article, *, base: str = "", vals=None) -> str:
    """Markdown نهایی با توکن‌های جایگزین‌شده و پیوندهای مطلق؛ برای خروجی ماشینی و دستیار."""
    return tokens.expand_links(tokens.resolve(article.body, vals), base)


def resolved_summary(article, vals=None) -> str:
    return tokens.resolve(article.summary, vals)


def resolve_titles(articles, vals=None):
    """عنوان مقاله‌ها گاهی توکن دارد (مثل {{site_name}}). نسخه‌ی درون‌حافظه‌ی عنوان را بدون توکن می‌کند؛
    مقاله ذخیره نمی‌شود، پس فایل و پایگاه داده دست‌نخورده می‌مانند."""
    items = [a for a in articles if a is not None]
    if not any("{{" in a.title for a in items):
        return
    vals = vals if vals is not None else tokens.values()
    for a in items:
        a.title = tokens.resolve(a.title, vals)


def attach_summaries(articles, vals=None):
    """خلاصه و عنوان بدون توکن را روی هر مقاله می‌گذارد (a.summary_text و a.title) تا کارت‌ها متن خام نشان ندهند.
    ورودی می‌تواند فهرست مقاله یا فهرست (مقاله، امتیاز) باشد؛ مقادیر یک بار خوانده می‌شود."""
    items = list(articles)
    if not items:
        return items
    vals = vals if vals is not None else tokens.values()
    arts = [item[0] if isinstance(item, tuple) else item for item in items]
    resolve_titles(arts, vals)
    for art in arts:
        art.summary_text = tokens.resolve(art.summary, vals)
    return items
