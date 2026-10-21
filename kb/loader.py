"""خواندن فایل‌های محتوای پایگاه دانش (kb/content) و همگام‌سازی با پایگاه داده.

هر مقاله یک فایل Markdown است: سرایند ساده (key: value) بین دو خط ---، سپس متن.
دسته از نام پوشه و شناسه (slug) از نام فایل می‌آید. فهرست دسته‌ها در _categories.json است.

همگام‌سازی ایمن است: مقاله‌ای که در پنل مدیریت ویرایش شده (locked) هرگز از فایل بازنویسی نمی‌شود.
"""
from __future__ import annotations

import datetime
import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from django.db import IntegrityError, transaction

from . import tokens
from .models import RESERVED_SLUGS, Article, Category

CONTENT_DIR = Path(__file__).resolve().parent / "content"
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,88}$")
KINDS = {k for k, _ in Article.Kind.choices}
AUDIENCES = {a for a, _ in Article.Audience.choices}
FIELDS = {"title", "summary", "kind", "audience", "keywords", "related", "featured", "order", "reviewed"}


@dataclass
class ArticleFile:
    slug: str
    category: str
    title: str
    summary: str
    body: str
    kind: str = "howto"
    audience: str = "public"
    keywords: str = ""
    related: list[str] = field(default_factory=list)
    featured: bool = False
    order: int = 100
    reviewed: datetime.date | None = None
    path: str = ""

    @property
    def digest(self) -> str:
        raw = json.dumps([self.category, self.title, self.summary, self.kind, self.audience, self.keywords,
                          self.related, self.featured, self.order, str(self.reviewed), self.body.strip()],
                         ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()


class ContentError(Exception):
    pass


def parse_file(path: Path, root: Path = CONTENT_DIR) -> ArticleFile:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"\A---\s*\n(.*?)\n---\s*\n?(.*)\Z", text, flags=re.S)
    if not m:
        raise ContentError(f"{path.name}: سرایند --- پیدا نشد.")
    meta: dict[str, str] = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition(":")
        if not sep:
            raise ContentError(f"{path.name}: خط سرایند نامعتبر است: {line!r}")
        meta[key.strip()] = value.strip()
    unknown = set(meta) - FIELDS
    if unknown:
        raise ContentError(f"{path.name}: کلید ناشناخته در سرایند: {', '.join(sorted(unknown))}")
    for req in ("title", "summary"):
        if not meta.get(req):
            raise ContentError(f"{path.name}: «{req}» لازم است.")
    reviewed = None
    if meta.get("reviewed"):
        try:
            reviewed = datetime.date.fromisoformat(meta["reviewed"])
        except ValueError as exc:
            raise ContentError(f"{path.name}: تاریخ reviewed باید YYYY-MM-DD باشد.") from exc
    try:
        order = int(meta.get("order", 100))
    except ValueError as exc:
        raise ContentError(f"{path.name}: order باید عدد باشد.") from exc
    rel = path.relative_to(root)
    return ArticleFile(
        slug=path.stem, category=rel.parts[0], title=meta["title"], summary=meta["summary"], body=m.group(2).strip(),
        kind=meta.get("kind", "howto"), audience=meta.get("audience", "public"),
        keywords=", ".join(k.strip() for k in re.split(r"[,،]", meta.get("keywords", "")) if k.strip()),
        related=[s.strip() for s in meta.get("related", "").split(",") if s.strip()],
        featured=meta.get("featured", "").lower() in ("yes", "true", "1", "بله"),
        order=order, reviewed=reviewed, path=str(rel))


def load_categories(root: Path = CONTENT_DIR) -> list[dict]:
    return json.loads((root / "_categories.json").read_text(encoding="utf-8"))


def load_articles(root: Path = CONTENT_DIR) -> list[ArticleFile]:
    return [parse_file(p, root) for p in sorted(root.glob("*/*.md"))]


def validate(root: Path = CONTENT_DIR) -> list[str]:
    """فهرست مشکل‌های محتوا (خالی = سالم)؛ هم در kb_check و هم در آزمون‌ها استفاده می‌شود."""
    problems: list[str] = []
    cats = {c["slug"] for c in load_categories(root)}
    try:
        files = load_articles(root)
    except ContentError as exc:
        return [str(exc)]
    slugs = [f.slug for f in files]
    for dup in {s for s in slugs if slugs.count(s) > 1}:
        problems.append(f"شناسه تکراری: {dup}")
    known = set(slugs)
    from core.help import GUIDE_MAP
    from core.views import DOC_SLUGS

    for f in files:
        where = f.path
        if not SLUG_RE.match(f.slug) or f.slug in RESERVED_SLUGS:
            problems.append(f"{where}: نام فایل (شناسه) نامعتبر یا رزرو است.")
        if f.category not in cats:
            problems.append(f"{where}: دسته «{f.category}» در _categories.json نیست.")
        if f.kind not in KINDS:
            problems.append(f"{where}: kind نامعتبر ({f.kind}).")
        if f.audience not in AUDIENCES:
            problems.append(f"{where}: audience نامعتبر ({f.audience}).")
        if len(f.summary) > 800:
            problems.append(f"{where}: پاسخ کوتاه بیش از ۸۰۰ نویسه است.")
        if len(f.title) > 200:
            problems.append(f"{where}: عنوان بیش از ۲۰۰ نویسه است.")
        if len(f.body) < 80:
            problems.append(f"{where}: متن مقاله بسیار کوتاه است.")
        for r in f.related:
            if r not in known:
                problems.append(f"{where}: مقاله مرتبط ناموجود: {r}")
            if r == f.slug:
                problems.append(f"{where}: مقاله با خودش مرتبط شده است.")
        for tok in sorted(tokens.unknown_tokens(f.summary + "\n" + f.body)):
            problems.append(f"{where}: توکن ناشناس {{{{{tok}}}}}")
        for kind, target in tokens.link_targets(f.summary + "\n" + f.body):
            ok = (target in known) if kind == "kb" else (target in GUIDE_MAP) if kind == "help" else (target in DOC_SLUGS)
            if not ok:
                problems.append(f"{where}: پیوند به {kind}:{target} پیدا نشد.")
    return problems


@dataclass
class SyncReport:
    created: list[str] = field(default_factory=list)
    updated: list[str] = field(default_factory=list)
    unchanged: int = 0
    locked: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    pruned: list[str] = field(default_factory=list)

    def summary(self) -> str:
        return (f"ساخته‌شده {len(self.created)}، به‌روز {len(self.updated)}، بدون تغییر {self.unchanged}، "
                f"قفل (ویرایش‌شده در پنل) {len(self.locked)}، تداخل با مقاله دستی {len(self.foreign)}، "
                f"پیش‌نویس‌شده {len(self.pruned)}")


def _apply(art: Article, f: ArticleFile, cat: Category):
    art.category = cat
    art.title, art.summary, art.body = f.title, f.summary, f.body
    art.kind, art.audience, art.keywords = f.kind, f.audience, f.keywords
    art.is_featured, art.order = f.featured, f.order
    if f.reviewed:
        art.reviewed_at = f.reviewed
    art.managed, art.locked, art.content_hash = True, False, f.digest


def sync(root: Path = CONTENT_DIR, *, force: bool = False, prune: bool = False, dry_run: bool = False) -> SyncReport:
    problems = validate(root)
    if problems:
        raise ContentError("؛ ".join(problems[:5]) + (" …" if len(problems) > 5 else ""))
    report = SyncReport()
    cats: dict[str, Category] = {}
    for c in load_categories(root):
        if dry_run:
            cats[c["slug"]] = Category(slug=c["slug"])
            continue
        obj, _ = Category.objects.update_or_create(slug=c["slug"], defaults={
            "title": c["title"], "description": c.get("description", ""), "icon": c.get("icon", ""),
            "order": c.get("order", 100)})
        cats[c["slug"]] = obj

    files = load_articles(root)
    touched: dict[str, ArticleFile] = {}
    for f in files:
        art = Article.objects.filter(slug=f.slug).first()
        if art is None:
            report.created.append(f.slug)
            touched[f.slug] = f
            if not dry_run:
                art = Article(slug=f.slug)
                _apply(art, f, cats[f.category])
                try:
                    with transaction.atomic():
                        art.save()
                except IntegrityError:  # راه‌اندازی هم‌زمان دو کانتینر
                    report.created.remove(f.slug)
            continue
        if not art.managed and not force:
            report.foreign.append(f.slug)
            continue
        if art.managed and art.locked and not force:
            report.locked.append(f.slug)
            continue
        if art.managed and art.content_hash == f.digest and not force:
            report.unchanged += 1
            continue
        report.updated.append(f.slug)
        touched[f.slug] = f
        if not dry_run:
            _apply(art, f, cats[f.category])
            art.save()

    if not dry_run:  # مقاله‌های مرتبط پس از ساخته شدن همه مقاله‌ها
        by_slug = {a.slug: a for a in Article.objects.filter(slug__in=[r for f in touched.values() for r in f.related]
                                                              + list(touched))}
        for slug, f in touched.items():
            art = by_slug.get(slug)
            if art:
                art.related.set([by_slug[r] for r in f.related if r in by_slug])
        if prune:
            wanted = {f.slug for f in files}
            for art in Article.objects.filter(managed=True).exclude(slug__in=wanted).exclude(
                    status=Article.Status.DRAFT):
                art.status = Article.Status.DRAFT
                art.save()
                report.pruned.append(art.slug)
    return report
