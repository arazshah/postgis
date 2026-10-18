import json
import re

from django.test import TestCase, override_settings


@override_settings(ALLOWED_HOSTS=["testserver", "postgis.ir", "postgis.araz.me", "www.postgis.ir"])
class SEOTests(TestCase):
    def jsonld(self, html):
        blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', html, re.S)
        return [json.loads(b) for b in blocks]

    def test_home_meta_and_structured_data(self):
        html = self.client.get("/").content.decode()
        self.assertIn('<link rel="canonical" href="https://postgis.ir/">', html)
        self.assertIn('content="index, follow"', html)
        self.assertIn("og:image", html)
        self.assertIn("پایگاه داده مکانی PostGIS", html.split("<title>")[1].split("</title>")[0])
        data = self.jsonld(html)
        types = {g["@type"] for g in data[0]["@graph"]}
        self.assertEqual(types, {"Organization", "WebSite", "SoftwareApplication", "VideoObject", "FAQPage"})
        faq = next(g for g in data[0]["@graph"] if g["@type"] == "FAQPage")
        for q in faq["mainEntity"]:
            self.assertIn(q["name"], html)  # پرسش‌های schema روی صفحه هم دیده می‌شوند

    def test_referrer_policy_sends_only_origin_to_external_payment_gateway(self):
        response = self.client.get("/")
        self.assertEqual(response["Referrer-Policy"], "strict-origin-when-cross-origin")

    def test_pillar_page(self):
        r = self.client.get("/docs/what-is-postgis/")
        self.assertEqual(r.status_code, 200)
        html = r.content.decode()
        self.assertIn("<h1>پایگاه داده مکانی و PostGIS چیست؟</h1>", html)
        types = [d.get("@type") or [g["@type"] for g in d["@graph"]] for d in self.jsonld(html)]
        self.assertIn(["TechArticle", "BreadcrumbList"], types)
        self.assertIn("FAQPage", types)

    def test_all_docs_have_valid_jsonld(self):
        from core.views import DOCS

        for slug, *_ in DOCS:
            html = self.client.get(f"/docs/{slug}/").content.decode()
            self.assertTrue(self.jsonld(html), slug)

    def test_robots_and_sitemap(self):
        r = self.client.get("/robots.txt")
        self.assertContains(r, "Disallow: /dashboard/")
        self.assertContains(r, "Sitemap: https://postgis.ir/sitemap.xml")
        r = self.client.get("/sitemap.xml")
        self.assertEqual(r["Content-Type"], "application/xml; charset=utf-8")
        body = r.content.decode()
        self.assertIn("<loc>https://postgis.ir/docs/what-is-postgis/</loc>", body)
        self.assertNotIn("/dashboard/", body)

    def test_private_pages_noindex(self):
        html = self.client.get("/accounts/login/").content.decode()
        self.assertIn('content="noindex, nofollow"', html)

    def test_secondary_domains_redirect(self):
        for host in ("postgis.araz.me", "www.postgis.ir"):
            r = self.client.get("/docs/qgis/?x=1", HTTP_HOST=host)
            self.assertEqual(r.status_code, 301)
            self.assertEqual(r["Location"], "https://postgis.ir/docs/qgis/?x=1")
        self.assertEqual(self.client.get("/", HTTP_HOST="postgis.ir").status_code, 200)
        # فرم‌ها (POST) دست نمی‌خورند
        self.assertNotEqual(self.client.post("/accounts/login/", {}, HTTP_HOST="postgis.araz.me").status_code, 301)
