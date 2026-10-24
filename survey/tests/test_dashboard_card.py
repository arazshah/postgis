from types import SimpleNamespace

from django.test import TestCase

from core.models import SiteSettings
from core.templatetags.ws import dash_actions


class DashboardCardTests(TestCase):
    def labels(self):
        groups = dash_actions(SimpleNamespace(pk=7))["groups"]
        return {i["label"]: i["url"] for g in groups for i in g["items"]}

    def test_card_hidden_while_flag_is_off(self):
        self.assertNotIn("برداشت میدانی", self.labels())

    def test_card_shown_when_flag_is_on_and_links_to_survey(self):
        conf = SiteSettings.get()
        conf.survey_enabled = True
        conf.save()
        self.assertEqual(self.labels()["برداشت میدانی"], "/dashboard/7/survey/")
