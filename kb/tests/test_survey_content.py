"""محتوای واقعی دسته «برداشت میدانی»: سالم، همگام‌شدنی و با توکن‌های پلن قابل نمایش."""
from django.test import TestCase, override_settings

from kb import loader
from kb.models import Article, Category

REQUIRED = {
    "survey-overview", "survey-first-project", "survey-capture-points", "survey-phone-gps", "survey-external-receiver",
    "survey-ntrip-rtk", "survey-offline", "survey-offline-basemap", "survey-import-export", "survey-cogo-stakeout",
    "survey-surface-contours", "survey-data-tables", "survey-api-sync", "survey-quota", "survey-troubleshooting",
}


@override_settings(ALLOWED_HOSTS=["testserver"])
class SurveyContentTests(TestCase):
    def test_content_is_valid_and_complete(self):
        self.assertEqual(loader.validate(), [])
        slugs = {a.slug for a in loader.load_articles() if a.category == "survey"}
        self.assertEqual(slugs, REQUIRED)

    def test_category_and_articles_render(self):
        loader.sync()
        self.assertTrue(Category.objects.filter(slug="survey").exists())
        self.assertEqual(Article.objects.filter(category__slug="survey").count(), len(REQUIRED))
        self.assertEqual(self.client.get("/kb/c/survey/").status_code, 200)
        for slug in REQUIRED:
            r = self.client.get(f"/kb/{slug}/")
            self.assertEqual(r.status_code, 200, slug)
            self.assertNotIn("{{", r.content.decode(), slug)

    def test_quota_article_resolves_plan_tokens(self):
        loader.sync()
        html = self.client.get("/kb/survey-quota/").content.decode()
        self.assertIn("پروژه", html)
        self.assertNotIn("plan_survey", html)
