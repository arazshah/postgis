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
