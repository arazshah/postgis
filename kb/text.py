"""ابزارهای متن فارسی برای پایگاه دانش: نرمال‌سازی، واژه‌بندی و تبدیل امن Markdown به HTML."""
from __future__ import annotations

import re

import markdown
from django.utils.safestring import mark_safe
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_CHAR_MAP = str.maketrans({"ي": "ی", "ى": "ی", "ك": "ک", "ۀ": "ه", "ة": "ه", "أ": "ا", "إ": "ا", "ؤ": "و"})
# اعراب، کشیده، نیم‌فاصله و نویسه‌های جهت‌دهی
_STRIP_RE = re.compile("[ً-ٰٟـ‌‍‎‏‪-‮﻿]")
_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)  # فقط حرف و رقم؛ «؟ ، ؛» جزو واژه نیست

# واژه‌هایی که جست‌وجو را بی‌خود سخت می‌کنند
STOPWORDS = frozenset("""
و در به از که را با این آن یک برای است هست می چه چطور چگونه چرا آیا کجا کی من ما شما او را یا اگر هم تا بر
باید شود شده کرد کنم کنید کند دارد دارم دارید نیست نه بله بعد قبل بین روی زیر مثل مثلا مثلاً
""".split())


def normalize(text: str) -> str:
    """یکسان‌سازی متن برای جست‌وجو: ی/ک عربی، ارقام، نیم‌فاصله، حروف بزرگ لاتین."""
    if not text:
        return ""
    text = text.translate(_CHAR_MAP).translate(_DIGITS)
    text = _STRIP_RE.sub("", text)
    return text.lower()


def tokens(text: str, *, drop_stop: bool = True) -> list[str]:
    out = []
    for w in _WORD_RE.findall(normalize(text)):
        if drop_stop and w in STOPWORDS:
            continue
        if len(w) < 2 and not w.isdigit():
            continue
        out.append(w)
    return out


def slugify(value: str, sep: str = "-") -> str:
    """شناسه عنوان برای لنگر (anchor)؛ حروف فارسی حفظ می‌شود."""
    value = normalize(str(value)).strip()
    value = re.sub(r"[^\w\s-]", "", value, flags=re.UNICODE)
    return re.sub(r"[\s_-]+", sep, value).strip(sep) or "section"


# ---------------- Markdown امن ----------------

_SAFE_URL = re.compile(r"^(https?://|mailto:|/|#)", re.IGNORECASE)


class _SafeLinks(Treeprocessor):
    """فقط پیوندهای http(s)، mailto، داخلی و لنگر؛ و تصویر فقط از /static/ یا https."""

    def run(self, root):
        for el in root.iter():
            if el.tag == "a":
                href = (el.get("href") or "").strip()
                if href and not _SAFE_URL.match(href):
                    el.set("href", "#")
                if href.lower().startswith("http"):
                    el.set("rel", "noopener nofollow")
                    el.set("target", "_blank")
            elif el.tag == "img":
                src = (el.get("src") or "").strip()
                if not (src.startswith("/static/") or src.lower().startswith("https://")):
                    el.set("src", "")


class _SafeExtension(Extension):
    def extendMarkdown(self, md):  # noqa: N802
        # HTML خام نوشته‌ی مقاله اجرا نمی‌شود؛ escape می‌شود
        md.preprocessors.deregister("html_block")
        md.inlinePatterns.deregister("html")
        md.treeprocessors.register(_SafeLinks(md), "kb_safe_links", 1)


def _md() -> markdown.Markdown:
    return markdown.Markdown(
        extensions=["fenced_code", "tables", "admonition", "sane_lists", "toc", _SafeExtension()],
        extension_configs={"toc": {"slugify": slugify, "toc_depth": "2-3", "permalink": False}},
        output_format="html",
    )


def render_markdown(source: str) -> tuple[str, list[tuple[int, str, str]]]:
    """(html امن، فهرست سرفصل‌ها به شکل (سطح، عنوان، لنگر))."""
    md = _md()
    html = md.convert(source or "")
    heads = [(t["level"], t["name"], t["id"]) for t in _flatten(md.toc_tokens)]
    return mark_safe(html), heads  # noqa: S308 — HTML خام پیش‌تر غیرفعال و پیوندها پالایش شده است


def _flatten(items):
    for it in items:
        yield it
        yield from _flatten(it.get("children", []))


def plain_text(source: str) -> str:
    """متن ساده مقاله (بدون نشانه‌گذاری) برای خلاصه‌ها و داده ساختاریافته."""
    s = re.sub(r"```.*?```", " ", source or "", flags=re.S)
    s = re.sub(r"`([^`]*)`", r"\1", s)
    s = re.sub(r"!\[[^\]]*\]\([^)]*\)", " ", s)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"^[#>\-\*\s|:]+", "", s, flags=re.M)
    s = re.sub(r"[*_|]{1,3}", "", s)
    return re.sub(r"\s+", " ", s).strip()
