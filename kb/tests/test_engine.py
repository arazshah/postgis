import json
import re
import tempfile
from pathlib import Path

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings

from databases.models import Plan
from kb import chunking, export, loader, search, tokens
from kb import text as fa
from kb.models import Article, ArticleChunk, Category, Feedback, MissedQuery

CATS = [{"slug": "start", "title": "شروع", "icon": "🚀", "order": 1, "description": "d"},
        {"slug": "tech", "title": "فنی", "icon": "🔧", "order": 2, "description": "d"}]


def write_article(root: Path, cat: str, slug: str, title="عنوان آزمایشی", summary="پاسخ کوتاه آزمایشی.", body=None,
                  **meta):
    d = root / cat
    d.mkdir(parents=True, exist_ok=True)
    head = {"title": title, "summary": summary, **meta}
    body = body or ("## بخش اول\n\nمتن بخش اول که به اندازه کافی طولانی است تا بررسی کیفیت محتوا آن را رد نکند، "
                    "و شامل چند جمله فارسی است.\n\n## بخش دوم\n\nمتن بخش دوم.")
    lines = "\n".join(f"{k}: {v}" for k, v in head.items())
    (d / f"{slug}.md").write_text(f"---\n{lines}\n---\n{body}\n", encoding="utf-8")


def make_root(**arts) -> Path:
    root = Path(tempfile.mkdtemp())
    (root / "_categories.json").write_text(json.dumps(CATS, ensure_ascii=False), encoding="utf-8")
    for slug, kw in arts.items():
        write_article(root, kw.pop("cat", "start"), slug, **kw)
    return root


class TextTests(TestCase):
    def test_normalize_unifies_persian_variants(self):
        self.assertEqual(fa.normalize("كيفيت ۱۲۳ ABC می‌شود"), "کیفیت 123 abc میشود")

    def test_tokens_drop_stopwords(self):
        self.assertEqual(fa.tokens("چطور پایگاه داده بسازم؟"), ["پایگاه", "داده", "بسازم"])

    def test_slugify_keeps_persian(self):
        self.assertEqual(fa.slugify("نام پایگاه داده؟"), "نام-پایگاه-داده")

    def test_markdown_escapes_raw_html_and_unsafe_links(self):
        html, _ = fa.render_markdown('<script>alert(1)</script>\n\n[x](javascript:alert(1)) [ok](https://a.ir) [in](/kb/x/)')
        self.assertNotIn("<script", html)
        self.assertIn("&lt;script", html)
        self.assertNotIn("javascript:", html)
        self.assertIn('href="https://a.ir"', html)
        self.assertIn('href="/kb/x/"', html)

    def test_markdown_unsafe_image_source_removed(self):
        html, _ = fa.render_markdown("![a](http://evil.example/x.png) ![b](/static/a.png)")
        self.assertNotIn("evil.example", html)
        self.assertIn('src="/static/a.png"', html)

    def test_headings_get_persian_anchors_and_toc(self):
        html, heads = fa.render_markdown("## بخش اول\n\nمتن\n\n### زیربخش\n\nمتن")
        self.assertEqual([(h[0], h[1]) for h in heads], [(2, "بخش اول"), (3, "زیربخش")])
        self.assertIn('id="بخش-اول"', html)

    def test_code_blocks_and_tables(self):
        html, _ = fa.render_markdown("| a | b |\n|---|---|\n| 1 | 2 |\n\n```sql\nSELECT 1;\n```")
        self.assertIn("<table>", html)
        self.assertIn("<pre><code", html)


class TokenTests(TestCase):
    def test_resolve_uses_default_plan(self):
        Plan.objects.all().delete()
        Plan.objects.create(name="آزمایشی", slug="t", quota_mb=2048, max_connections=7, duration_days=30,
                            is_default=True)
        out = tokens.resolve("{{plan_name}}|{{plan_quota}}|{{plan_connections}}|{{plan_days}}")
        self.assertEqual(out, "آزمایشی|۲ گیگابایت|۷|۳۰")

    def test_resolve_without_plan_uses_defaults(self):
        Plan.objects.all().delete()
        self.assertEqual(tokens.resolve("{{plan_quota}}"), "۱ گیگابایت")

    def test_unknown_token_left_visible_and_reported(self):
        self.assertEqual(tokens.resolve("x {{nope}} y"), "x {{nope}} y")
        self.assertEqual(tokens.unknown_tokens("{{nope}} {{plan_name}}"), {"nope"})

    def test_plans_table_lists_public_plans_only(self):
        Plan.objects.all().delete()
        Plan.objects.create(name="عمومی", slug="a", price_toman=150000, is_free=False, is_public=True)
        Plan.objects.create(name="مخفی", slug="b", is_public=False)
        table = tokens.resolve("{{plans_table}}")
        self.assertIn("عمومی", table)
        self.assertIn("۱۵۰٬۰۰۰ تومان", table)
        self.assertNotIn("مخفی", table)

    def test_link_shorthand(self):
        out = tokens.expand_links("[a](kb:x) [b](help:y#z) [c](doc:w)", base="https://s.ir")
        self.assertEqual(out, "[a](https://s.ir/kb/x/) [b](https://s.ir/help/y/#z) [c](https://s.ir/docs/w/)")


class ChunkTests(TestCase):
    def test_first_chunk_is_summary_and_sections_have_anchors(self):
        body = "مقدمه\n\n## بخش اول\n\n" + "الف " * 120 + "\n\n## بخش دوم\n\n" + "ب " * 150
        chunks = chunking.build_chunks("عنوان", "پاسخ کوتاه", body)
        self.assertEqual(chunks[0]["ordinal"], 0)
        self.assertIn("پاسخ کوتاه", chunks[0]["text"])
        self.assertIn("مقدمه", chunks[0]["text"])
        self.assertEqual([c["heading"] for c in chunks[1:]], ["بخش اول", "بخش دوم"])
        self.assertEqual(chunks[1]["anchor"], "بخش-اول")

    def test_short_sections_merge(self):
        chunks = chunking.build_chunks("ع", "پ", "## الف\n\nکوتاه\n\n## ب\n\nکوتاه")
        self.assertEqual(len(chunks), 2)
        self.assertIn("الف", chunks[1]["heading"])
        self.assertIn("ب", chunks[1]["heading"])

    def test_headings_inside_code_are_ignored(self):
        chunks = chunking.build_chunks("ع", "پ", "## اصلی\n\n```\n## not heading\n```\n\nمتن")
        self.assertEqual([c["heading"] for c in chunks[1:]], ["اصلی"])

    def test_long_section_is_split(self):
        para = "جمله " * 150
        chunks = chunking.build_chunks("ع", "پ", "## بزرگ\n\n" + "\n\n".join([para] * 4))
        self.assertGreater(len(chunks), 2)
        self.assertTrue(all(len(c["text"]) <= chunking.MAX_CHARS + 200 for c in chunks))

    def test_saving_article_rebuilds_chunks(self):
        cat = Category.objects.create(slug="c", title="دسته")
        a = Article.objects.create(slug="a1", category=cat, title="ع", summary="پ", body="## یک\n\nمتن یک")
        self.assertEqual(a.chunks.count(), 2)
        a.body = "## یک\n\n" + "متن " * 100 + "\n\n## دو\n\nمتن دو که کمی بلندتر است " + "و " * 200
        a.save()
        self.assertEqual({c.heading for c in a.chunks.all()}, {"ع", "یک", "دو"})


class LoaderTests(TestCase):
    def test_sync_creates_and_is_idempotent(self):
        root = make_root(one={"related": "two", "keywords": "الف, ب"}, two={"cat": "tech", "featured": "yes"})
        r1 = loader.sync(root)
        self.assertEqual(sorted(r1.created), ["one", "two"])
        r2 = loader.sync(root)
        self.assertEqual((r2.created, r2.updated, r2.unchanged), ([], [], 2))
        one = Article.objects.get(slug="one")
        self.assertEqual([a.slug for a in one.related.all()], ["two"])
        self.assertTrue(Article.objects.get(slug="two").is_featured)
        self.assertEqual(one.keyword_list(), ["الف", "ب"])

    def test_file_change_updates_article(self):
        root = make_root(one={})
        loader.sync(root)
        write_article(root, "start", "one", title="عنوان تازه")
        report = loader.sync(root)
        self.assertEqual(report.updated, ["one"])
        self.assertEqual(Article.objects.get(slug="one").title, "عنوان تازه")

    def test_panel_edit_is_never_overwritten(self):
        root = make_root(one={})
        loader.sync(root)
        Article.objects.filter(slug="one").update(locked=True, title="ویرایش پنل")
        write_article(root, "start", "one", title="عنوان فایل")
        report = loader.sync(root)
        self.assertEqual(report.locked, ["one"])
        self.assertEqual(Article.objects.get(slug="one").title, "ویرایش پنل")
        loader.sync(root, force=True)
        self.assertEqual(Article.objects.get(slug="one").title, "عنوان فایل")

    def test_manual_article_with_same_slug_not_touched(self):
        root = make_root(one={})
        cat = Category.objects.create(slug="start", title="x")
        Article.objects.create(slug="one", category=cat, title="دستی", summary="پ")
        report = loader.sync(root)
        self.assertEqual(report.foreign, ["one"])
        self.assertEqual(Article.objects.get(slug="one").title, "دستی")

    def test_prune_drafts_missing_files(self):
        root = make_root(one={}, two={})
        loader.sync(root)
        (root / "start" / "two.md").unlink()
        report = loader.sync(root, prune=True)
        self.assertEqual(report.pruned, ["two"])
        self.assertEqual(Article.objects.get(slug="two").status, Article.Status.DRAFT)

    def test_dry_run_writes_nothing(self):
        root = make_root(one={})
        report = loader.sync(root, dry_run=True)
        self.assertEqual(report.created, ["one"])
        self.assertEqual(Article.objects.count(), 0)

    def test_validate_reports_problems(self):
        root = make_root(one={"related": "ghost", "kind": "bad"},
                         two={"body": "کوتاه"}, three={"body": "## الف\n\n" + "متن " * 40 + "{{unknown_x}} [l](kb:nothing)"})
        problems = "\n".join(loader.validate(root))
        self.assertIn("ghost", problems)
        self.assertIn("kind نامعتبر", problems)
        self.assertIn("بسیار کوتاه", problems)
        self.assertIn("unknown_x", problems)
        self.assertIn("kb:nothing", problems)

    def test_reserved_slug_rejected(self):
        root = make_root(search={})
        self.assertTrue(any("رزرو" in p for p in loader.validate(root)))

    def test_sync_refuses_invalid_content(self):
        root = make_root(one={"related": "ghost"})
        with self.assertRaises(loader.ContentError):
            loader.sync(root)
        self.assertEqual(Article.objects.count(), 0)

    def test_missing_header_is_error(self):
        root = make_root()
        (root / "start").mkdir(exist_ok=True)
        (root / "start" / "bad.md").write_text("بدون سرایند", encoding="utf-8")
        self.assertTrue(loader.validate(root))


class RealContentTests(TestCase):
    """محتوای واقعی مخزن همیشه سالم باشد؛ خطای پیوند یا توکن در CI دیده می‌شود."""

    def test_content_is_valid(self):
        self.assertEqual(loader.validate(), [])

    def test_content_syncs_and_renders(self):
        report = loader.sync()
        self.assertGreater(len(report.created), 0)
        for art in Article.objects.all():
            self.assertTrue(art.chunks.exists(), art.slug)
        again = loader.sync()
        self.assertEqual((again.created, again.updated), ([], []))


class SearchTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cat = Category.objects.create(slug="c", title="دسته")
        mk = Article.objects.create
        cls.a_pub = mk(slug="connect-error", category=cat, title="چرا خطای Connection refused می‌گیرم؟",
                       summary="پورت را از جدول اطلاعات اتصال کپی کنید.", body="## علت\n\nپورت اشتباه است.",
                       keywords="رد شدن اتصال, پورت 5432")
        cls.a_body = mk(slug="backup", category=cat, title="بکاپ شبانه", summary="هر شب بکاپ گرفته می‌شود.",
                        body="## جزئیات\n\nدر صورت خطا بکاپ را بازگردانید.")
        cls.a_member = mk(slug="member-only", category=cat, title="تنظیمات ویژه اتصال", summary="ویژه اعضا.",
                          audience=Article.Audience.MEMBER)
        cls.a_staff = mk(slug="staff-only", category=cat, title="راه‌اندازی داخلی اتصال", summary="ویژه مدیران.",
                         audience=Article.Audience.STAFF)
        cls.a_draft = mk(slug="draft", category=cat, title="اتصال پیش‌نویس", summary="x",
                         status=Article.Status.DRAFT)

    def titles(self, q, user=None):
        return [a.slug for a, _ in search.search(q, user)]

    def test_title_match_ranks_first(self):
        self.assertEqual(self.titles("خطای اتصال پورت")[0], "connect-error")

    def test_persian_variants_and_digits(self):
        self.assertIn("connect-error", self.titles("پورت ۵۴۳۲"))
        self.assertIn("connect-error", self.titles("کانکشن Connection REFUSED"))

    def test_audience_visibility(self):
        anon = self.titles("اتصال")
        self.assertNotIn("member-only", anon)
        self.assertNotIn("staff-only", anon)
        self.assertNotIn("draft", anon)
        User = get_user_model()
        member = User.objects.create_user(phone="09120000001")
        staff = User.objects.create_admin(username="s", password="pw-12345-Ab", superuser=False)
        self.assertIn("member-only", self.titles("اتصال", member))
        self.assertNotIn("staff-only", self.titles("اتصال", member))
        self.assertIn("staff-only", self.titles("اتصال", staff))
        self.assertNotIn("draft", self.titles("اتصال", staff))

    def test_or_fallback_when_few_and_matches(self):
        self.assertIn("backup", self.titles("بکاپ اتصال"))

    def test_empty_and_stopword_only_queries(self):
        self.assertEqual(self.titles(""), [])
        self.assertEqual(self.titles("چطور و در"), [])

    def test_log_missed_counts_without_user_data(self):
        search.log_missed("چیزی که نیست")
        search.log_missed("چیزی  که  نیست")
        row = MissedQuery.objects.get()
        self.assertEqual(row.count, 2)
        search.log_missed("ab")
        self.assertEqual(MissedQuery.objects.count(), 1)


@override_settings(ALLOWED_HOSTS=["testserver", "postgis.ir"])
class ViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.root = make_root(
            alpha={"title": "پرسش اول", "summary": "پاسخ اول با {{plan_quota}} حجم.", "kind": "faq", "featured": "yes",
                   "keywords": "نمونه"},
            beta={"cat": "tech", "title": "راهنمای دوم", "kind": "howto", "related": "alpha"},
            memb={"title": "ویژه اعضا", "audience": "member"},
            intern={"cat": "tech", "title": "داخلی مدیران", "audience": "staff"})
        loader.sync(cls.root)
        User = get_user_model()
        cls.member = User.objects.create_user(phone="09120000002")
        cls.staff = User.objects.create_admin(username="adm", password="pw-12345-Ab", superuser=False)

    def jsonld(self, html):
        return [json.loads(b) for b in re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)]

    def test_index_lists_categories_and_featured(self):
        r = self.client.get("/kb/")
        self.assertContains(r, "پایگاه دانش")
        self.assertContains(r, "پرسش اول")
        self.assertNotContains(r, "ویژه اعضا")
        self.assertNotContains(r, "داخلی مدیران")
        self.assertEqual(self.jsonld(r.content.decode())[0]["@type"], "WebSite")

    def test_article_renders_answer_tokens_and_jsonld(self):
        r = self.client.get("/kb/alpha/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("پاسخ اول با ۱ گیگابایت حجم.", html)
        graph = self.jsonld(html)[0]["@graph"]
        self.assertEqual({g["@type"] for g in graph}, {"BreadcrumbList", "FAQPage"})
        self.assertIn('<link rel="canonical" href="https://postgis.ir/kb/alpha/">', html)
        self.assertIn("index, follow", html)

    def test_howto_uses_techarticle(self):
        graph = self.jsonld(self.client.get("/kb/beta/").content.decode())[0]["@graph"]
        self.assertIn("TechArticle", {g["@type"] for g in graph})

    def test_related_shown(self):
        self.assertContains(self.client.get("/kb/beta/"), "پرسش اول")

    def test_member_article_requires_login(self):
        r = self.client.get("/kb/memb/")
        self.assertEqual(r.status_code, 302)
        self.assertIn("/accounts/login/", r["Location"])
        self.client.force_login(self.member)
        r = self.client.get("/kb/memb/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("noindex", r.content.decode())

    def test_staff_article_hidden_from_everyone_but_staff(self):
        self.assertEqual(self.client.get("/kb/intern/").status_code, 404)
        self.client.force_login(self.member)
        self.assertEqual(self.client.get("/kb/intern/").status_code, 404)
        self.client.force_login(self.staff)
        self.assertEqual(self.client.get("/kb/intern/").status_code, 200)

    def test_draft_visible_only_to_staff(self):
        Article.objects.filter(slug="beta").update(status=Article.Status.DRAFT)
        self.assertEqual(self.client.get("/kb/beta/").status_code, 404)
        self.client.force_login(self.staff)
        r = self.client.get("/kb/beta/")
        self.assertContains(r, "پیش‌نویس")

    def test_unknown_and_reserved_slugs_404(self):
        self.assertEqual(self.client.get("/kb/nothing/").status_code, 404)
        self.assertEqual(self.client.get("/kb/c/nothing/").status_code, 404)

    def test_category_page(self):
        r = self.client.get("/kb/c/tech/")
        self.assertContains(r, "راهنمای دوم")
        self.assertNotContains(r, "داخلی مدیران")

    def test_search_results_and_noindex(self):
        r = self.client.get("/kb/search/", {"q": "پرسش"})
        self.assertContains(r, "پرسش اول")
        self.assertIn("noindex", r.content.decode())

    def test_search_miss_logs_and_offers_support(self):
        r = self.client.get("/kb/search/", {"q": "موضوع ناموجود"})
        self.assertContains(r, "پیدا نشد")
        self.assertEqual(MissedQuery.objects.get().sample, "موضوع ناموجود")

    def test_search_escapes_query(self):
        r = self.client.get("/kb/search/", {"q": "<script>x</script>"})
        self.assertNotContains(r, "<script>x</script>")

    def test_feedback_once_per_session(self):
        r = self.client.post("/kb/alpha/feedback/", {"helpful": "1"}, follow=True)
        self.assertContains(r, "ممنون")
        self.client.post("/kb/alpha/feedback/", {"helpful": "0", "comment": "x"})
        self.assertEqual(Feedback.objects.count(), 1)
        self.assertTrue(Feedback.objects.get().helpful)

    def test_feedback_requires_post(self):
        self.assertEqual(self.client.get("/kb/alpha/feedback/").status_code, 405)

    def test_feedback_on_hidden_article_blocked(self):
        self.assertEqual(self.client.post("/kb/intern/feedback/", {"helpful": "1"}).status_code, 404)

    def test_api_articles_public_only(self):
        data = self.client.get("/kb/api/articles.json").json()
        slugs = {a["id"] for a in data["articles"]}
        self.assertEqual(slugs, {"alpha", "beta"})
        self.assertNotIn("body_markdown", data["articles"][0])
        full = self.client.get("/kb/api/articles.json", {"full": "1"}).json()["articles"][0]
        self.assertIn("body_markdown", full)
        self.assertTrue(full["url"].startswith("https://postgis.ir/kb/"))

    def test_api_chunks_jsonl(self):
        r = self.client.get("/kb/api/chunks.jsonl")
        rows = [json.loads(line) for line in r.content.decode().splitlines()]
        self.assertTrue(rows)
        self.assertTrue(all(row["article"] in {"alpha", "beta"} for row in rows))
        self.assertIn("۱ گیگابایت", next(row for row in rows if row["id"] == "alpha#0")["text"])

    def test_llms_txt(self):
        r = self.client.get("/llms.txt")
        self.assertContains(r, "https://postgis.ir/kb/alpha/")
        self.assertNotContains(r, "kb/intern")
        full = self.client.get("/llms-full.txt").content.decode()
        self.assertIn("پاسخ کوتاه", full)
        self.assertNotIn("داخلی مدیران", full)

    def test_sitemap_has_kb_public_pages_only(self):
        body = self.client.get("/sitemap.xml").content.decode()
        self.assertIn("<loc>https://postgis.ir/kb/</loc>", body)
        self.assertIn("<loc>https://postgis.ir/kb/alpha/</loc>", body)
        self.assertNotIn("/kb/memb/", body)
        self.assertNotIn("/kb/intern/", body)

    def test_robots_blocks_search_pages(self):
        self.assertContains(self.client.get("/robots.txt"), "Disallow: /kb/search/")

    def test_home_faq_comes_from_featured_articles(self):
        html = self.client.get("/").content.decode()
        self.assertIn("پرسش اول", html)
        self.assertIn('href="/kb/alpha/"', html)
        graph = self.jsonld(html)[0]["@graph"]
        faq = next(g for g in graph if g["@type"] == "FAQPage")
        self.assertEqual([q["name"] for q in faq["mainEntity"]], ["پرسش اول"])
        self.assertIn("۱ گیگابایت", faq["mainEntity"][0]["acceptedAnswer"]["text"])

    def test_nav_links_to_kb(self):
        self.assertContains(self.client.get("/"), 'href="/kb/"')


class HomeFallbackTests(TestCase):
    def test_home_faq_falls_back_when_no_featured_articles(self):
        html = self.client.get("/").content.decode()
        self.assertIn("پایگاه داده مکانی چیست؟", html)


@override_settings(ALLOWED_HOSTS=["testserver", "postgis.ir"])
class AdminTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        User = get_user_model()
        cls.admin = User.objects.create_superuser(username="root", password="pw-12345-Ab")
        loader.sync(make_root(one={}))

    def test_admin_edit_locks_managed_article(self):
        self.client.force_login(self.admin)
        art = Article.objects.get(slug="one")
        self.assertFalse(art.locked)
        data = {"title": "ویرایش دستی", "slug": "one", "category": art.category_id, "kind": art.kind,
                "audience": art.audience, "status": art.status, "summary": art.summary, "body": art.body,
                "keywords": "", "order": art.order, "reviewed_at": str(art.reviewed_at),
                "article_chunks-TOTAL_FORMS": 0, "article_chunks-INITIAL_FORMS": 0}
        data.update({"chunks-TOTAL_FORMS": 0, "chunks-INITIAL_FORMS": 0})
        r = self.client.post(f"/manage/kb/article/{art.pk}/change/", data)
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        art.refresh_from_db()
        self.assertEqual(art.title, "ویرایش دستی")
        self.assertTrue(art.locked)

    def test_export_requires_staff_and_includes_internal(self):
        loader.sync(make_root(one={}, hidden={"audience": "staff"}))
        self.assertEqual(self.client.get("/manage/kb/article/export/").status_code, 302)
        self.client.force_login(self.admin)
        r = self.client.get("/manage/kb/article/export/", {"audience": "all"})
        self.assertEqual(r.status_code, 200)
        rows = [json.loads(line) for line in r.content.decode().splitlines()]
        self.assertIn("hidden", {row["article"] for row in rows})

    def test_changelist_shows_export_link(self):
        self.client.force_login(self.admin)
        self.assertContains(self.client.get("/manage/kb/article/"), "خروجی JSONL")


class ExportTests(TestCase):
    def test_chunk_rows_resolve_tokens_and_anchor_urls(self):
        loader.sync(make_root(one={"summary": "حجم {{plan_quota}}",
                                   "body": "## بخش\n\nمتن [پیوند](kb:one) " + "کلمه " * 80}))
        rows = list(export.chunk_rows("public"))
        self.assertTrue(any("۱ گیگابایت" in r["text"] for r in rows))
        sec = next(r for r in rows if r["heading"] == "بخش")
        self.assertTrue(sec["url"].endswith("/kb/one/#بخش"))
        self.assertIn("/kb/one/", sec["text"])
        self.assertTrue(sec["embedding_text"].startswith("عنوان آزمایشی"))

    def test_audience_levels(self):
        loader.sync(make_root(pub1={}, mem1={"audience": "member"}, stf1={"audience": "staff"}))
        ids = lambda aud: {r["id"] for r in export.article_rows(aud)}  # noqa: E731
        self.assertEqual(ids("public"), {"pub1"})
        self.assertEqual(ids("member"), {"pub1", "mem1"})
        self.assertEqual(ids("all"), {"pub1", "mem1", "stf1"})

    def test_chunks_cascade_on_delete(self):
        loader.sync(make_root(pub1={}))
        Article.objects.all().delete()
        self.assertEqual(ArticleChunk.objects.count(), 0)
