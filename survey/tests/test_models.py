from django.db import IntegrityError, transaction
from django.test import TestCase

from core.models import SiteSettings
from databases.models import Plan, UserDatabase
from survey.models import GnssDriver, SurveyProject


class SurveyFoundationTests(TestCase):
    def test_flag_is_off_by_default(self):
        self.assertFalse(SiteSettings().survey_enabled)

    def test_free_plan_defaults_are_tight(self):
        plan = Plan()
        self.assertEqual((plan.survey_projects, plan.survey_max_points, plan.gnss_external), (1, 200, False))

    def test_driver_id_and_version_are_unique(self):
        GnssDriver.objects.create(driver_id="nmea-generic", version="1.0.0", api_version=1)
        with self.assertRaises(IntegrityError), transaction.atomic():
            GnssDriver.objects.create(driver_id="nmea-generic", version="1.0.0", api_version=1)
        GnssDriver.objects.create(driver_id="nmea-generic", version="1.1.0", api_version=1)

    def test_project_model_declares_unique_slug_per_database(self):
        names = {c.name for c in SurveyProject._meta.constraints}
        self.assertIn("survey_project_db_slug_uniq", names)
        self.assertTrue(UserDatabase._meta.get_field("plan"))
