"""هیچ توکن پویای خام ({{plan_quota}} و مانند آن) نباید روی صفحه یا خروجی عمومی بماند."""
import re

from django.test import TestCase, override_settings

from kb import loader
from kb.models import Article

RAW_TOKEN = re.compile(r"\{\{\s*[a-z0-9_]+\s*\}\}")


@override_settings(ALLOWED_HOSTS=["testserver", "postgis.ir"])
class PublicTokensTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        loader.sync(force=True)

    def assertClean(self, path):
        r = self.client.get(path)
        self.assertEqual(r.status_code, 200, path)
        found = RAW_TOKEN.findall(r.content.decode())
        self.assertEqual(found, [], f"توکن خام در {path}: {found[:3]}")

    def test_kb_index_cards(self):
        self.assertClean("/kb/")

    def test_kb_category_pages(self):
        for slug in Article.objects.values_list("category__slug", flat=True).distinct():
            self.assertClean(f"/kb/c/{slug}/")

    def test_kb_search_cards(self):
        self.assertClean("/kb/search/?q=پلن+رایگان")

    def test_home_page_and_faq_jsonld(self):
        self.assertClean("/")

    def test_machine_outputs(self):
        for path in ("/llms.txt", "/llms-full.txt", "/kb/api/articles.json", "/kb/api/chunks.jsonl"):
            self.assertClean(path)

    def test_free_plan_card_shows_real_values(self):
        html = self.client.get("/kb/search/?q=پلن+رایگان+محدودیت").content.decode()
        self.assertIn("free-plan-limits", html)
        self.assertNotIn("{{plan_", html)
